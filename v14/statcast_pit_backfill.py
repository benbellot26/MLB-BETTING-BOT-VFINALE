from __future__ import annotations

"""Strict point-in-time Statcast backfill for V14 research.

This module uses V14-native provider and aggregation primitives. It fetches a
bounded Baseball Savant detailed CSV, dedupes stable-ID pitch rows, then applies
the V14 enrichment layer. For cutoff D only rows with game_date < D may
contribute. Output remains research-only and cannot auto-promote a champion.
"""

import argparse
import csv
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable

from .provider_http import http_text
from .statcast_base import STATCAST_ROW_CAP, dedupe_statcast_rows
from .statcast_enrichment import aggregate_statcast_priors

ROLE="RESEARCH_ONLY"
DEFAULT_OUTPUT=Path("runtime/v14/statcast_pit")
FetchChunk=Callable[...,tuple[list[dict[str,str]],dict[str,Any]]]
STATCAST_MAX_CHUNK_DAYS=3


def _chunks(start:date,end:date,days:int=3):
    cur=start
    while cur<=end:
        stop=min(end,cur+timedelta(days=days-1));yield cur,stop;cur=stop+timedelta(days=1)


def _normalize_row(row:dict[str,Any])->dict[str,Any]:
    out:dict[str,Any]={}
    for key,value in row.items():
        if key is None:continue
        normalized=str(key).lstrip("\ufeff").strip()
        if normalized:out[normalized]=value
    return out


def _query_params(start_day:str,end_day:str,season:int)->dict[str,Any]:
    return {"all":"true","hfPT":"","hfAB":"","hfBBT":"","hfPR":"","hfZ":"","stadium":"","hfBBL":"","hfNewZones":"","hfGT":"R|","hfSea":f"{int(season)}|","hfSit":"","player_type":"pitcher","hfOuts":"","opponent":"","pitcher_throws":"","batter_stands":"","hfSA":"","game_date_gt":start_day,"game_date_lt":end_day,"team":"","position":"","hfRO":"","home_road":"","hfFlag":"","metric_1":"","hfInn":"","min_pitches":0,"min_results":0,"min_pas":0,"min_abs":0,"group_by":"name","sort_col":"pitches","player_event_sort":"h_launch_speed","sort_order":"desc","type":"details"}


def _fetch_statcast_rows_full(start_day:str,end_day:str,*,season:int,fetch_text:Callable[...,str]|None=None)->list[dict[str,str]]:
    fetch_text=fetch_text or http_text
    text=fetch_text("https://baseballsavant.mlb.com/statcast_search/csv",_query_params(start_day,end_day,season),timeout=45)
    rows=[_normalize_row(row) for row in csv.DictReader(io.StringIO((text or "").lstrip("\ufeff")))]
    if rows:
        columns=set(rows[0]);required={"game_date","batter","pitcher","pitch_type","stand","p_throws"}
        if not required.issubset(columns):raise ValueError(f"unexpected Statcast detailed CSV schema; missing={sorted(required-columns)}")
    return rows


def _fetch_statcast_rows_adaptive_v14(start_day:str,end_day:str,*,season:int,row_cap:int=STATCAST_ROW_CAP,fetch_text:Callable[...,str]|None=None)->tuple[list[dict[str,str]],dict[str,Any]]:
    start=date.fromisoformat(start_day);end=date.fromisoformat(end_day)
    if end<start:raise ValueError("statcast end_day before start_day")
    if (end-start).days+1>STATCAST_MAX_CHUNK_DAYS:raise ValueError(f"adaptive statcast root exceeds {STATCAST_MAX_CHUNK_DAYS} days")
    diagnostics:dict[str,Any]={"requests":[],"cap_hits":0,"splits":0,"unresolved_truncation":False,"query_contract":"SAVANT_COMPLETE_DETAILS_V2","required_handedness_fields":["stand","p_throws"]}
    def _fetch(a:date,b:date)->list[dict[str,str]]:
        rows=_fetch_statcast_rows_full(a.isoformat(),b.isoformat(),season=season,fetch_text=fetch_text);capped=len(rows)>=int(row_cap);diagnostics["requests"].append({"start":a.isoformat(),"end":b.isoformat(),"rows":len(rows),"cap_hit":capped})
        if not capped:return rows
        diagnostics["cap_hits"]+=1
        if a>=b:diagnostics["unresolved_truncation"]=True;raise RuntimeError(f"statcast_single_day_row_cap:{a.isoformat()}:{len(rows)}")
        span=(b-a).days+1;left_days=max(1,span//2);left_end=a+timedelta(days=left_days-1);right_start=left_end+timedelta(days=1);diagnostics["splits"]+=1;return _fetch(a,left_end)+_fetch(right_start,b)
    rows=dedupe_statcast_rows(_fetch(start,end));diagnostics["deduped_rows"]=len(rows);diagnostics["requests_made"]=len(diagnostics["requests"]);return rows,diagnostics


def _hash_rows(rows:list[dict[str,Any]])->str:
    h=hashlib.sha256()
    for row in sorted(rows,key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),str(r.get("at_bat_number") or ""),str(r.get("pitch_number") or ""),str(r.get("batter") or ""),str(r.get("pitcher") or ""))):h.update((json.dumps(row,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode("utf-8"))
    return h.hexdigest()


def build(cutoff_day:str,*,season_start:str|None=None,fetch_chunk:FetchChunk=_fetch_statcast_rows_adaptive_v14)->dict[str,Any]:
    cutoff=date.fromisoformat(str(cutoff_day)[:10]);season=cutoff.year;start=date.fromisoformat(season_start) if season_start else date(season,3,1);end=cutoff-timedelta(days=1)
    if start>=cutoff:raise ValueError("season_start must be before cutoff")
    rows=[];requests=[]
    for a,b in _chunks(start,end,3):
        chunk,diag=fetch_chunk(a.isoformat(),b.isoformat(),season=season);rows.extend(_normalize_row(row) for row in chunk);requests.append({"start":a.isoformat(),"end":b.isoformat(),"diagnostics":diag})
    rows=dedupe_statcast_rows(rows);bad=[r for r in rows if str(r.get("game_date") or "")[:10]>=cutoff.isoformat()]
    if bad:raise ValueError(f"future/current-day Statcast rows present before aggregation: {len(bad)}")
    priors=aggregate_statcast_priors(rows,cutoff.isoformat());max_dates=[]
    for bucket in (priors.get("hitters") or {},priors.get("pitchers") or {}):max_dates.extend(str(v.get("max_game_date")) for v in bucket.values() if v.get("max_game_date"))
    if max_dates and max(max_dates)>=cutoff.isoformat():raise ValueError("aggregated Statcast prior crossed cutoff")
    diag=priors.get("diagnostics") or {}
    return {"schema":"pulsar-v14-statcast-pit-backfill-v4","role":ROLE,"auto_activation":False,"point_in_time":True,"stable_id_only":True,"cutoff_day":cutoff.isoformat(),"source_start":start.isoformat(),"source_end":end.isoformat(),"source":"Baseball Savant Statcast complete details CSV + V14-native pitch/handedness enrichment","provider_query_contract":"SAVANT_COMPLETE_DETAILS_V2","header_normalization":"UTF-8 BOM and outer whitespace stripped from provider CSV keys","raw_pitch_rows":len(rows),"raw_rows_sha256":_hash_rows(rows),"requests":requests,"priors":priors,"coverage":{"hitters":len(priors.get("hitters") or {}),"pitchers":len(priors.get("pitchers") or {}),"hitter_pitch_split_players":int(diag.get("hitter_pitch_split_players") or 0),"hitter_pitch_split_buckets":int(diag.get("hitter_pitch_split_buckets") or 0),"hitter_pitcher_hand_split_players":int(diag.get("hitter_pitcher_hand_split_players") or 0),"pitcher_batter_side_split_players":int(diag.get("pitcher_batter_side_split_players") or 0)},"champion_impact":False,"native_live_confirmation_required":True}


def write(cutoff_day:str,output:Path|str,*,season_start:str|None=None,fetch_chunk:FetchChunk=_fetch_statcast_rows_adaptive_v14)->dict[str,Any]:
    artifact=build(cutoff_day,season_start=season_start,fetch_chunk=fetch_chunk);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser(description="Build strict enriched PIT Statcast priors for a historical cutoff");parser.add_argument("cutoff_day");parser.add_argument("--season-start");parser.add_argument("--output");args=parser.parse_args();output=args.output or str(DEFAULT_OUTPUT/f"statcast_{args.cutoff_day}.json");out=write(args.cutoff_day,output,season_start=args.season_start);print(json.dumps({"schema":out["schema"],"cutoff_day":out["cutoff_day"],"raw_pitch_rows":out["raw_pitch_rows"],"coverage":out.get("coverage"),"raw_rows_sha256":out["raw_rows_sha256"]},sort_keys=True))


if __name__=="__main__":main()
