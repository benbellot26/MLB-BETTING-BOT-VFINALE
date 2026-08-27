from __future__ import annotations

"""V14-native Statcast enrichment for research challengers.

The base artifact provides stable-ID hitter/pitcher priors and pitcher pitch mix.
This layer adds hitter skill by exact pitch type and by opposing pitcher hand,
plus pitcher allowed-quality splits by batter side. All buckets obey the same
strict ``game_date < cutoff`` contract. No batter-vs-pitcher head-to-head record
is created and all downstream use remains shadow-only until OOS promotion.
"""

from collections import defaultdict
from datetime import date
import math
from typing import Any

from .statcast_base import aggregate_statcast_priors as aggregate_base
from .statcast_base import dedupe_statcast_rows

SCHEMA="pulsar-v14-statcast-id-priors-v2"


def _num(value:Any)->float|None:
    try:out=float(value)
    except Exception:return None
    return out if math.isfinite(out) else None


def _empty()->dict[str,Any]:
    return {"pitches":0,"pa":0,"strikeouts":0,"walks":0,"swings":0,"whiffs":0,"xwoba_sum":0.0,"xwoba_n":0,"ev_sum":0.0,"ev_n":0,"hard_hit":0,"barrels":0,"max_game_date":None}


def _consume(stat:dict[str,Any],row:dict[str,Any])->None:
    stat["pitches"]+=1;gd=str(row.get("game_date") or "")
    if gd and (not stat["max_game_date"] or gd>stat["max_game_date"]):stat["max_game_date"]=gd
    event=str(row.get("events") or "").strip().lower()
    if event:
        stat["pa"]+=1
        if event.startswith("strikeout"):stat["strikeouts"]+=1
        if event in {"walk","intent_walk","intentional_walk"}:stat["walks"]+=1
    description=str(row.get("description") or "").strip().lower()
    if description in {"swinging_strike","swinging_strike_blocked","foul","foul_tip","hit_into_play","hit_into_play_no_out","hit_into_play_score","missed_bunt","foul_bunt"}:stat["swings"]+=1
    if description in {"swinging_strike","swinging_strike_blocked","missed_bunt"}:stat["whiffs"]+=1
    xwoba=_num(row.get("estimated_woba_using_speedangle"))
    if xwoba is not None and 0.0<=xwoba<=1.0:stat["xwoba_sum"]+=xwoba;stat["xwoba_n"]+=1
    ev=_num(row.get("launch_speed"))
    if ev is not None and 20.0<=ev<=130.0:
        stat["ev_sum"]+=ev;stat["ev_n"]+=1
        if ev>=95.0:stat["hard_hit"]+=1
        if str(row.get("launch_speed_angle") or "").strip()=="6":stat["barrels"]+=1


def _finalize(stat:dict[str,Any])->dict[str,Any]:
    pa=int(stat["pa"]);evn=int(stat["ev_n"]);swings=int(stat["swings"])
    return {"pitches":int(stat["pitches"]),"pa":pa,"k_rate":stat["strikeouts"]/pa if pa else None,"bb_rate":stat["walks"]/pa if pa else None,"k_minus_bb_rate":(stat["strikeouts"]-stat["walks"])/pa if pa else None,"xwoba":stat["xwoba_sum"]/stat["xwoba_n"] if stat["xwoba_n"] else None,"xwoba_batted_balls":int(stat["xwoba_n"]),"avg_exit_velocity":stat["ev_sum"]/evn if evn else None,"hard_hit_rate":stat["hard_hit"]/evn if evn else None,"barrel_rate":stat["barrels"]/evn if evn else None,"batted_balls":evn,"swings":swings,"whiffs":int(stat["whiffs"]),"whiff_rate":stat["whiffs"]/swings if swings else None,"max_game_date":stat["max_game_date"]}


def _split_rows(rows:list[dict[str,Any]],cutoff_day:str,*,entity_key:str,split_key:str,allowed:set[str]|None=None)->dict[str,dict[str,dict[str,Any]]]:
    cutoff=date.fromisoformat(str(cutoff_day)[:10]);buckets:dict[str,dict[str,dict[str,Any]]]=defaultdict(dict)
    for row in dedupe_statcast_rows(rows):
        try:gd=date.fromisoformat(str(row.get("game_date") or "")[:10])
        except Exception:continue
        if gd>=cutoff:continue
        entity=str(row.get(entity_key) or "").strip();split=str(row.get(split_key) or "").strip().upper()
        if not entity.isdigit() or not split or (allowed is not None and split not in allowed):continue
        stat=buckets[entity].setdefault(split,_empty());_consume(stat,row)
    return {pid:{key:_finalize(stat) for key,stat in sorted(values.items())} for pid,values in sorted(buckets.items())}


def hitter_pitch_type_splits(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,dict[str,dict[str,Any]]]:
    return _split_rows(rows,cutoff_day,entity_key="batter",split_key="pitch_type")


def hitter_pitcher_hand_splits(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,dict[str,dict[str,Any]]]:
    return _split_rows(rows,cutoff_day,entity_key="batter",split_key="p_throws",allowed={"L","R"})


def pitcher_batter_side_splits(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,dict[str,dict[str,Any]]]:
    return _split_rows(rows,cutoff_day,entity_key="pitcher",split_key="stand",allowed={"L","R"})


def aggregate_statcast_priors(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,Any]:
    base=aggregate_base(rows,cutoff_day);pitch_splits=hitter_pitch_type_splits(rows,cutoff_day);hand_splits=hitter_pitcher_hand_splits(rows,cutoff_day);batter_side_splits=pitcher_batter_side_splits(rows,cutoff_day)
    hitters={}
    for pid,row in (base.get("hitters") or {}).items():
        item=dict(row);item["pitch_type_splits"]=pitch_splits.get(str(pid),{});item["pitcher_hand_splits"]=hand_splits.get(str(pid),{});hitters[str(pid)]=item
    pitchers={}
    for pid,row in (base.get("pitchers") or {}).items():
        item=dict(row);item["batter_side_splits"]=batter_side_splits.get(str(pid),{});pitchers[str(pid)]=item
    split_players=sum(1 for row in hitters.values() if row.get("pitch_type_splits"));split_pitch_buckets=sum(len(row.get("pitch_type_splits") or {}) for row in hitters.values());hand_players=sum(1 for row in hitters.values() if row.get("pitcher_hand_splits"));pitcher_side_players=sum(1 for row in pitchers.values() if row.get("batter_side_splits"))
    diagnostics=dict(base.get("diagnostics") or {});diagnostics.update({"hitter_pitch_split_players":split_players,"hitter_pitch_split_buckets":split_pitch_buckets,"hitter_pitcher_hand_split_players":hand_players,"pitcher_batter_side_split_players":pitcher_side_players,"pitch_split_definition":"exact Statcast pitch_type; terminal PA outcomes plus pitch-level swing/contact metrics; consumer shrinkage required","handedness_definition":"official Statcast p_throws and stand fields; stable-ID aggregate only; no head-to-head"})
    return {**base,"schema":SCHEMA,"hitters":hitters,"pitchers":pitchers,"diagnostics":diagnostics,"v14_enrichment":{"hitter_pitch_type_splits":True,"hitter_pitcher_hand_splits":True,"pitcher_batter_side_splits":True,"head_to_head_used":False,"consumer_shrinkage_required":True,"exact_pitch_type_codes":True,"statcast_handedness_fields":["p_throws","stand"]}}
