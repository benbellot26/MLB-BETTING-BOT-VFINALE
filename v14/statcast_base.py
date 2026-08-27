from __future__ import annotations

"""Native V14 Statcast primitives shared by live and historical research paths.

This module intentionally contains no model logic. It only normalizes stable-ID
pitch rows, removes exact pitch duplicates, enforces a strict cutoff, and builds
basic hitter/pitcher priors. Keeping these primitives in V14 removes a legacy
V11/V13 dependency from the current Statcast data pipeline.
"""

from collections import Counter, defaultdict
from datetime import date
import math
from typing import Any

STATCAST_ROW_CAP=25_000
SCHEMA="pulsar-v14-statcast-base-priors-v1"


def _num(value:Any,default:float|None=None)->float|None:
    try:
        out=float(value)
        return out if math.isfinite(out) else default
    except Exception:return default


def _event(row:dict[str,Any])->str:return str(row.get("events") or "").strip().lower()


def _pitch_key(row:dict[str,Any])->tuple[str,...]:
    return tuple(str(row.get(k) or "") for k in ("game_pk","at_bat_number","pitch_number","batter","pitcher","game_date"))


def dedupe_statcast_rows(rows:list[dict[str,Any]])->list[dict[str,Any]]:
    seen:set[tuple[str,...]]=set();out=[]
    for row in rows:
        key=_pitch_key(row)
        if key in seen:continue
        seen.add(key);out.append(row)
    return out


def _empty_stat()->dict[str,Any]:
    return {"pitches":0,"pa":0,"strikeouts":0,"walks":0,"xwoba_sum":0.0,"xwoba_n":0,"ev_sum":0.0,"ev_n":0,"hard_hit":0,"barrels":0,"velocity_sum":0.0,"velocity_n":0,"pitch_types":Counter(),"max_game_date":None}


def _consume_common(stat:dict[str,Any],row:dict[str,Any])->None:
    stat["pitches"]+=1;gd=str(row.get("game_date") or "")
    if gd and (not stat["max_game_date"] or gd>stat["max_game_date"]):stat["max_game_date"]=gd
    event=_event(row)
    if event:
        stat["pa"]+=1
        if event.startswith("strikeout"):stat["strikeouts"]+=1
        if event in {"walk","intent_walk","intentional_walk"}:stat["walks"]+=1
    xwoba=_num(row.get("estimated_woba_using_speedangle"))
    if xwoba is not None and 0.0<=xwoba<=1.0:stat["xwoba_sum"]+=xwoba;stat["xwoba_n"]+=1
    ev=_num(row.get("launch_speed"))
    if ev is not None and 20.0<=ev<=130.0:
        stat["ev_sum"]+=ev;stat["ev_n"]+=1
        if ev>=95.0:stat["hard_hit"]+=1
        if str(row.get("launch_speed_angle") or "").strip()=="6":stat["barrels"]+=1


def _finalize_stat(stat:dict[str,Any],include_pitching:bool=False)->dict[str,Any]:
    pa=int(stat["pa"]);ev_n=int(stat["ev_n"])
    out={"pitches":int(stat["pitches"]),"pa":pa,"k_rate":stat["strikeouts"]/pa if pa else None,"bb_rate":stat["walks"]/pa if pa else None,"k_minus_bb_rate":(stat["strikeouts"]-stat["walks"])/pa if pa else None,"xwoba":stat["xwoba_sum"]/stat["xwoba_n"] if stat["xwoba_n"] else None,"xwoba_batted_balls":int(stat["xwoba_n"]),"avg_exit_velocity":stat["ev_sum"]/ev_n if ev_n else None,"hard_hit_rate":stat["hard_hit"]/ev_n if ev_n else None,"barrel_rate":stat["barrels"]/ev_n if ev_n else None,"batted_balls":ev_n,"max_game_date":stat["max_game_date"]}
    if include_pitching:
        mix=stat["pitch_types"];total=sum(mix.values());out["avg_release_speed"]=stat["velocity_sum"]/stat["velocity_n"] if stat["velocity_n"] else None;out["velocity_pitches"]=int(stat["velocity_n"]);out["pitch_mix"]={k:v/total for k,v in sorted(mix.items())} if total else {}
    return out


def aggregate_statcast_priors(rows:list[dict[str,Any]],cutoff_day:str)->dict[str,Any]:
    cutoff=date.fromisoformat(str(cutoff_day)[:10]);hitters:dict[str,dict[str,Any]]=defaultdict(_empty_stat);pitchers:dict[str,dict[str,Any]]=defaultdict(_empty_stat);accepted=rejected_future=rejected_bad_date=0
    for row in dedupe_statcast_rows(rows):
        try:gd=date.fromisoformat(str(row.get("game_date") or "")[:10])
        except Exception:rejected_bad_date+=1;continue
        if gd>=cutoff:rejected_future+=1;continue
        batter=str(row.get("batter") or "").strip();pitcher=str(row.get("pitcher") or "").strip()
        if batter.isdigit():_consume_common(hitters[batter],row)
        if pitcher.isdigit():
            p=pitchers[pitcher];_consume_common(p,row);velo=_num(row.get("release_speed"))
            if velo is not None and 40.0<=velo<=110.0:p["velocity_sum"]+=velo;p["velocity_n"]+=1
            ptype=str(row.get("pitch_type") or "").strip().upper()
            if ptype:p["pitch_types"][ptype]+=1
        accepted+=1
    return {"schema":SCHEMA,"cohort":"PULSAR_V14_RESEARCH_PIT","cutoff_day":cutoff.isoformat(),"point_in_time":True,"stable_id_only":True,"source":"Baseball Savant Statcast Search CSV","hitters":{pid:_finalize_stat(s) for pid,s in sorted(hitters.items())},"pitchers":{pid:_finalize_stat(s,include_pitching=True) for pid,s in sorted(pitchers.items())},"diagnostics":{"accepted_pitch_rows":accepted,"rejected_at_or_after_cutoff":rejected_future,"rejected_bad_game_date":rejected_bad_date}}
