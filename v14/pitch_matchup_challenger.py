from __future__ import annotations

"""Pitch-arsenal × lineup-skill matchup challenger.

This intentionally avoids batter-vs-pitcher head-to-head records. It combines
the opponent starter's pitch usage with each hitter's shrinkable performance by
pitch family, weights hitters by batting-order opportunity, and reports an
independent pitcher-handedness matchup diagnostic when PIT Statcast splits exist.
All outputs remain challenger-only and have zero champion impact.
"""

import math
from typing import Any

ROLE="CHALLENGER_ONLY"
ORDER_WEIGHTS=(1.04,1.05,1.08,1.10,1.06,1.00,.96,.93,.90)


def _num(v:Any)->float|None:
    try:out=float(v)
    except Exception:return None
    return out if math.isfinite(out) else None


def _normalize_mix(mix:dict[str,Any])->dict[str,float]:
    rows={str(k).upper():float(v) for k,v in mix.items() if _num(v) is not None and float(v)>0};total=sum(rows.values());return {k:v/total for k,v in rows.items()} if total>0 else {}


def _split_value(block:dict[str,Any])->float|None:
    for key in ("xwoba","xwOBA","woba","rv100","run_value_per_100"):
        value=_num(block.get(key))
        if value is not None:
            if key in {"rv100","run_value_per_100"}:return .320+value*.012
            return value
    return None


def _shrunk_split(block:dict[str,Any],k:float)->float|None:
    value=_split_value(block)
    if value is None:return None
    pa=int(_num(block.get("pa") or block.get("pitches") or 0) or 0);reliability=pa/(pa+k);return reliability*value+(1-reliability)*.320


def hitter_vs_mix(pitch_splits:dict[str,Any],mix:dict[str,float])->tuple[float|None,float]:
    values=[];coverage=0.0
    for pitch,usage in mix.items():
        split=pitch_splits.get(pitch) or pitch_splits.get(pitch.lower()) or {}
        if not isinstance(split,dict):continue
        shrunk=_shrunk_split(split,80.0)
        if shrunk is None:continue
        values.append((shrunk,usage));coverage+=usage
    if not values or coverage<=0:return None,coverage
    return sum(v*w for v,w in values)/coverage,coverage


def build_side(*,lineup:dict[str,Any],starter_shadow:dict[str,Any],hitters_artifact:dict[str,Any])->dict[str,Any]:
    mix=_normalize_mix(starter_shadow.get("pitch_mix") or {})
    if not mix:return {"status":"COLLECTING","reason":"starter_pitch_mix_missing","role":ROLE,"auto_activation":False}
    starter_hand=str(starter_shadow.get("pitch_hand") or "").upper();starter_hand=starter_hand if starter_hand in {"L","R"} else None;rows=[]
    for i,player in enumerate((lineup.get("players") or [])[:9]):
        pid=str(player.get("id") or "");prior=hitters_artifact.get(pid) or {};splits=prior.get("pitch_type_splits") or prior.get("arsenal_splits") or {};value,coverage=hitter_vs_mix(splits,mix);hand_value=None
        if starter_hand:
            block=(prior.get("pitcher_hand_splits") or {}).get(starter_hand) or {}
            if isinstance(block,dict):hand_value=_shrunk_split(block,100.0)
        if value is not None:rows.append({"id":pid,"batting_order":i+1,"order_weight":ORDER_WEIGHTS[min(i,8)],"matchup_xwoba":value,"pitch_mix_coverage":coverage,"pitcher_hand":starter_hand,"handedness_xwoba":hand_value})
    if len(rows)<5:return {"status":"COLLECTING","reason":"lineup_pitch_type_coverage_insufficient","covered_hitters":len(rows),"role":ROLE,"auto_activation":False,"starter_pitch_mix":mix,"starter_pitch_hand":starter_hand}
    denom=sum(r["order_weight"] for r in rows);weighted=sum(r["matchup_xwoba"]*r["order_weight"] for r in rows)/denom;coverage=sum(r["pitch_mix_coverage"]*r["order_weight"] for r in rows)/denom;hand_rows=[r for r in rows if r.get("handedness_xwoba") is not None];hand_denom=sum(r["order_weight"] for r in hand_rows);handedness=sum(float(r["handedness_xwoba"])*r["order_weight"] for r in hand_rows)/hand_denom if hand_denom>0 else None
    return {"schema":"pulsar-v14-pitch-matchup-challenger-v2","status":"READY_SHADOW","role":ROLE,"auto_activation":False,"covered_hitters":len(rows),"lineup_order_weighted":True,"mean_pitch_mix_coverage":coverage,"matchup_xwoba":weighted,"matchup_index":max(-1.0,min(1.0,(weighted-.320)/.055)),"starter_pitch_mix":mix,"starter_pitch_hand":starter_hand,"handedness_covered_hitters":len(hand_rows),"handedness_xwoba":handedness,"handedness_index":max(-1.0,min(1.0,(handedness-.320)/.055)) if handedness is not None else None,"handedness_combined_into_primary":False,"players":rows,"head_to_head_used":False,"market_probability_used_as_feature":False}


def build(feature_row:dict[str,Any],statcast_shadow:dict[str,Any],artifact:dict[str,Any])->dict[str,Any]:
    if not artifact or artifact.get("point_in_time") is not True:return {"schema":"pulsar-v14-pitch-matchup-challenger-v2","role":ROLE,"auto_activation":False,"status":"COLLECTING","reason":"PIT statcast artifact unavailable"}
    ctx=feature_row.get("context") or {};hitters=artifact.get("hitters") or {};home=build_side(lineup=ctx.get("home_lineup") or {},starter_shadow=((statcast_shadow.get("away") or {}).get("starter") or {}),hitters_artifact=hitters);away=build_side(lineup=ctx.get("away_lineup") or {},starter_shadow=((statcast_shadow.get("home") or {}).get("starter") or {}),hitters_artifact=hitters)
    return {"schema":"pulsar-v14-pitch-matchup-challenger-v2","role":ROLE,"auto_activation":False,"status":"READY_SHADOW" if home.get("status")=="READY_SHADOW" and away.get("status")=="READY_SHADOW" else "COLLECTING","home_offense":home,"away_offense":away,"head_to_head_used":False,"handedness_combined_into_primary":False,"champion_impact":False}
