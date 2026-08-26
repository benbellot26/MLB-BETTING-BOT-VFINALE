from __future__ import annotations

"""Strict point-in-time Statcast backfill for V14 research.

This module is deliberately outside the native-production import boundary. It
reuses the audited V137 Savant fetch/dedupe primitives, then applies the V14
enrichment layer that adds shrinkable hitter pitch-type splits. It never calls
current-season summary endpoints for an old game. For a cutoff D, only pitch
rows with game_date < D may contribute. Output is research-only and cannot
auto-promote a champion.
"""

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from v11.v137_free_data import dedupe_statcast_rows, fetch_statcast_rows_adaptive
from .statcast_enrichment import aggregate_statcast_priors

ROLE="RESEARCH_ONLY"
DEFAULT_OUTPUT=Path("runtime/v14/statcast_pit")
FetchChunk=Callable[...,tuple[list[dict[str,str]],dict[str,Any]]]


def _chunks(start:date,end:date,days:int=3):
    cur=start
    while cur<=end:
        stop=min(end,cur+timedelta(days=days-1));yield cur,stop;cur=stop+timedelta(days=1)


def _normalize_row(row:dict[str,Any])->dict[str,Any]:
    """Normalize provider CSV headers without altering values.

    Baseball Savant CSV downloads may carry a UTF-8 BOM on the first header
    (normally ``pitch_type``). ``csv.DictReader`` preserves that BOM in the key,
    which silently makes ``row.get('pitch_type')`` empty while the rest of the
    row remains usable. Strip BOM/outer whitespace from every key at the V14
    ingestion boundary so pitch-mix enrichment uses the documented schema.
    """
    out:dict[str,Any]={}
    for key,value in row.items():
        if key is None:
            continue
        normalized=str(key).lstrip("\ufeff").strip()
        if normalized:
            out[normalized]=value
    return out


def _hash_rows(rows:list[dict[str,Any]])->str:
    h=hashlib.sha256()
    for row in sorted(rows,key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or ""),str(r.get("at_bat_number") or ""),str(r.get("pitch_number") or ""),str(r.get("batter") or ""),str(r.get("pitcher") or ""))):
        h.update((json.dumps(row,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n").encode("utf-8"))
    return h.hexdigest()


def build(cutoff_day:str,*,season_start:str|None=None,fetch_chunk:FetchChunk=fetch_statcast_rows_adaptive)->dict[str,Any]:
    cutoff=date.fromisoformat(str(cutoff_day)[:10]);season=cutoff.year;start=date.fromisoformat(season_start) if season_start else date(season,3,1);end=cutoff-timedelta(days=1)
    if start>=cutoff:raise ValueError("season_start must be before cutoff")
    rows=[];requests=[]
    for a,b in _chunks(start,end,3):
        chunk,diag=fetch_chunk(a.isoformat(),b.isoformat(),season=season)
        rows.extend(_normalize_row(row) for row in chunk);requests.append({"start":a.isoformat(),"end":b.isoformat(),"diagnostics":diag})
    rows=dedupe_statcast_rows(rows)
    bad=[r for r in rows if str(r.get("game_date") or "")[:10]>=cutoff.isoformat()]
    if bad:raise ValueError(f"future/current-day Statcast rows present before aggregation: {len(bad)}")
    priors=aggregate_statcast_priors(rows,cutoff.isoformat())
    max_dates=[]
    for bucket in (priors.get("hitters") or {},priors.get("pitchers") or {}):
        max_dates.extend(str(v.get("max_game_date")) for v in bucket.values() if v.get("max_game_date"))
    if max_dates and max(max_dates)>=cutoff.isoformat():raise ValueError("aggregated Statcast prior crossed cutoff")
    diag=priors.get("diagnostics") or {}
    return {"schema":"pulsar-v14-statcast-pit-backfill-v2","role":ROLE,"auto_activation":False,"point_in_time":True,"stable_id_only":True,"cutoff_day":cutoff.isoformat(),"source_start":start.isoformat(),"source_end":end.isoformat(),"source":"Baseball Savant Statcast Search CSV via V137 audited bounded fetcher + V14 pitch-type enrichment","header_normalization":"UTF-8 BOM and outer whitespace stripped from provider CSV keys","raw_pitch_rows":len(rows),"raw_rows_sha256":_hash_rows(rows),"requests":requests,"priors":priors,"coverage":{"hitters":len(priors.get("hitters") or {}),"pitchers":len(priors.get("pitchers") or {}),"hitter_pitch_split_players":int(diag.get("hitter_pitch_split_players") or 0),"hitter_pitch_split_buckets":int(diag.get("hitter_pitch_split_buckets") or 0)},"champion_impact":False,"native_live_confirmation_required":True}


def write(cutoff_day:str,output:Path|str,*,season_start:str|None=None,fetch_chunk:FetchChunk=fetch_statcast_rows_adaptive)->dict[str,Any]:
    artifact=build(cutoff_day,season_start=season_start,fetch_chunk=fetch_chunk);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser(description="Build strict enriched PIT Statcast priors for a historical cutoff")
    parser.add_argument("cutoff_day");parser.add_argument("--season-start");parser.add_argument("--output")
    args=parser.parse_args();output=args.output or str(DEFAULT_OUTPUT/f"statcast_{args.cutoff_day}.json");out=write(args.cutoff_day,output,season_start=args.season_start)
    print(json.dumps({"schema":out["schema"],"cutoff_day":out["cutoff_day"],"raw_pitch_rows":out["raw_pitch_rows"],"coverage":out.get("coverage"),"raw_rows_sha256":out["raw_rows_sha256"]},sort_keys=True))


if __name__=="__main__":main()