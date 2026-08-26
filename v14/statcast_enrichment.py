from __future__ import annotations

"""V14 Statcast enrichment on top of the audited V137 PIT aggregator.

The V137 artifact already provides stable-ID overall hitter/pitcher priors and
pitcher pitch mix. V14 additionally needs hitter skill by pitch type for the
arsenal-matchup challenger. Those splits are built from the same deduplicated
pitch rows under the same strict ``game_date < cutoff`` contract.

No batter-vs-pitcher head-to-head statistic is created. Exact Statcast pitch
codes are retained so the hitter split keys and pitcher pitch-mix keys share a
single provider vocabulary. Small samples are intentionally preserved: the
consumer performs hierarchical shrinkage rather than hard filtering here.
"""

from collections import defaultdict
from datetime import date
import math
from typing import Any

from v11.v137_free_data import aggregate_statcast_priors as aggregate_base
from v11.v137_free_data import dedupe_statcast_rows

SCHEMA="pulsar-v14-statcast-id-priors-v2"


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _empty()->dict[str,Any]:
    return {"pitches":0,"pa":0,"strikeouts":0,"walks":0,"swings":0,"whiffs":0,"xwoba_sum":0.0,"xwoba_n":0,"ev_sum":0.0,"ev_n":0,"hard_hit":0,"barrels":0,"max_game_date":None}


def _consume(stat:dict[str,Any],row:dict[str,Any])->None:
    stat["pitches"]+=1
    gd=str(row.get("game_date") or "")
    if gd and (not stat["max_game_date"] or gd>stat["max_game_date"]): stat["max_game_date"]=gd
    event=str(row.get("events") or "").strip().lower()
    if event:
        stat["pa"]+=1
        if event.startswith("strikeout"): stat["strikeouts"]+=1
        if event in {"walk","intent_walk","intentional_walk"}: stat["walks"]+=1
    description=str(row.get("description") or "").strip().lower()
    if description in {"swinging_strike","swinging_strike_blocked","foul","foul_tip","hit_into_play","hit_into_play_no_out","hit_into_play_score","missed_bunt","foul_bunt"}:
        stat["swings"]+=1
    if description in {"swinging_strike","swinging_strike_blocked","missed_bunt"}:
        stat["whiffs"]+=1
    xwoba=_num(row.get("estimated_woba_using_speedangle"))
    if xwoba is not None and 0.0<=xwoba<=1.0:
        stat["xwoba_sum"]+=xwoba; stat["xwoba_n"]+=1
    ev=_num(row.get("launch_speed"))
    if ev is not None and 20.0<=ev<=130.0:
        stat["ev_sum"]+=ev; stat["ev_n"]+=1
        if ev>=95.0: stat["hard_hit"]+=1
        if str(row.get("launch_speed_angle") or "").strip()=="6": stat["barrels"]+=1


def _finalize(stat:dict[str,Any])->dict[str,Any]:
    pa=int(stat["pa"]); evn=int(stat["ev_n"]); swings=int(stat["swings"])
    return {
        "pitches":int(stat["pitches"]),"pa":pa,
        "k_rate":stat["strikeouts"]/pa if pa else None,
        "bb_rate":stat["walks"]/pa if pa else None,
        "k_minus_bb_rate":(stat["strikeouts"]-stat["walks"])/pa if pa else None,
        "xwoba":stat["xwoba_sum"]/stat["xwoba_n"] if stat["xwoba_n"] else None,
        "xwoba_batted_balls":int(stat["xwoba_n"]),
        "avg_exit_velocity":stat["ev_sum"]/evn if evn else None,
        "hard_hit_rate":stat["hard_hit"]/evn if evn else None,
        "barrel_rate":stat["barrels"]/evn if evn else None,
        "batted_balls":evn,"swings":swings,"whiffs":int(stat["whiffs"]),
        "whiff_rate":stat["whiffs"]/swings if swings else None,
        "max_game_date":stat["max_game_date"],
    }


def hitter_pitch_type_splits(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,dict[str,dict[str,Any]]]:
    cutoff=date.fromisoformat(str(cutoff_day)[:10]); buckets:dict[str,dict[str,dict[str,Any]]]=defaultdict(dict)
    for row in dedupe_statcast_rows(rows):
        try: gd=date.fromisoformat(str(row.get("game_date") or "")[:10])
        except Exception: continue
        if gd>=cutoff: continue
        batter=str(row.get("batter") or "").strip(); pitch=str(row.get("pitch_type") or "").strip().upper()
        if not batter.isdigit() or not pitch: continue
        stat=buckets[batter].setdefault(pitch,_empty()); _consume(stat,row)
    return {pid:{pitch:_finalize(stat) for pitch,stat in sorted(pitches.items())} for pid,pitches in sorted(buckets.items())}


def aggregate_statcast_priors(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,Any]:
    base=aggregate_base(rows,cutoff_day); splits=hitter_pitch_type_splits(rows,cutoff_day)
    hitters={}
    for pid,row in (base.get("hitters") or {}).items():
        item=dict(row); item["pitch_type_splits"]=splits.get(str(pid),{}); hitters[str(pid)]=item
    split_players=sum(1 for row in hitters.values() if row.get("pitch_type_splits")); split_pitch_buckets=sum(len(row.get("pitch_type_splits") or {}) for row in hitters.values())
    diagnostics=dict(base.get("diagnostics") or {}); diagnostics.update({"hitter_pitch_split_players":split_players,"hitter_pitch_split_buckets":split_pitch_buckets,"pitch_split_definition":"exact Statcast pitch_type; terminal PA outcomes plus pitch-level swing/contact metrics; consumer shrinkage required"})
    return {**base,"schema":SCHEMA,"hitters":hitters,"diagnostics":diagnostics,"v14_enrichment":{"hitter_pitch_type_splits":True,"head_to_head_used":False,"consumer_shrinkage_required":True,"exact_pitch_type_codes":True}}
