from __future__ import annotations

"""Pitch-arsenal × lineup-skill matchup challenger.

This intentionally avoids batter-vs-pitcher head-to-head records.  It combines
the opponent starter's pitch usage with each hitter's shrinkable performance by
pitch family when those PIT splits exist in the Statcast artifact.
"""

import math
from typing import Any

ROLE="CHALLENGER_ONLY"


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _normalize_mix(mix:dict[str,Any])->dict[str,float]:
    rows={str(k).upper():float(v) for k,v in mix.items() if _num(v) is not None and float(v)>0}; total=sum(rows.values())
    return {k:v/total for k,v in rows.items()} if total>0 else {}


def _split_value(block:dict[str,Any])->float|None:
    for key in ("xwoba","xwOBA","woba","rv100","run_value_per_100"):
        value=_num(block.get(key))
        if value is not None:
            # Normalize RV/100-like values onto an xwOBA-ish centered scale only
            # for ranking; the result remains a dimensionless shadow diagnostic.
            if key in {"rv100","run_value_per_100"}: return .320+value*.012
            return value
    return None


def hitter_vs_mix(pitch_splits:dict[str,Any],mix:dict[str,float])->tuple[float|None,float]:
    values=[]; coverage=0.0
    for pitch,usage in mix.items():
        split=pitch_splits.get(pitch) or pitch_splits.get(pitch.lower()) or {}
        if not isinstance(split,dict): continue
        value=_split_value(split)
        if value is None: continue
        pa=int(_num(split.get("pa") or split.get("pitches") or 0) or 0); reliability=pa/(pa+80.0); shrunk=reliability*value+(1-reliability)*.320
        values.append((shrunk,usage)); coverage+=usage
    if not values or coverage<=0: return None,coverage
    return sum(v*w for v,w in values)/coverage,coverage


def build_side(*,lineup:dict[str,Any],starter_shadow:dict[str,Any],hitters_artifact:dict[str,Any])->dict[str,Any]:
    mix=_normalize_mix(starter_shadow.get("pitch_mix") or {})
    if not mix: return {"status":"COLLECTING","reason":"starter_pitch_mix_missing","role":ROLE,"auto_activation":False}
    rows=[]
    for player in (lineup.get("players") or [])[:9]:
        pid=str(player.get("id") or ""); prior=hitters_artifact.get(pid) or {}; splits=prior.get("pitch_type_splits") or prior.get("arsenal_splits") or {}
        value,coverage=hitter_vs_mix(splits,mix)
        if value is not None: rows.append({"id":pid,"matchup_xwoba":value,"pitch_mix_coverage":coverage})
    if len(rows)<5: return {"status":"COLLECTING","reason":"lineup_pitch_type_coverage_insufficient","covered_hitters":len(rows),"role":ROLE,"auto_activation":False,"starter_pitch_mix":mix}
    weighted=sum(r["matchup_xwoba"] for r in rows)/len(rows); coverage=sum(r["pitch_mix_coverage"] for r in rows)/len(rows)
    return {"schema":"pulsar-v14-pitch-matchup-challenger-v1","status":"READY_SHADOW","role":ROLE,"auto_activation":False,"covered_hitters":len(rows),"mean_pitch_mix_coverage":coverage,"matchup_xwoba":weighted,"matchup_index":max(-1.0,min(1.0,(weighted-.320)/.055)),"starter_pitch_mix":mix,"players":rows,"head_to_head_used":False,"market_probability_used_as_feature":False}


def build(feature_row:dict[str,Any],statcast_shadow:dict[str,Any],artifact:dict[str,Any])->dict[str,Any]:
    if not artifact or artifact.get("point_in_time") is not True: return {"schema":"pulsar-v14-pitch-matchup-challenger-v1","role":ROLE,"auto_activation":False,"status":"COLLECTING","reason":"PIT statcast artifact unavailable"}
    ctx=feature_row.get("context") or {}; hitters=artifact.get("hitters") or {}
    # Home hitters face Away starter and vice versa.
    home=build_side(lineup=ctx.get("home_lineup") or {},starter_shadow=((statcast_shadow.get("away") or {}).get("starter") or {}),hitters_artifact=hitters)
    away=build_side(lineup=ctx.get("away_lineup") or {},starter_shadow=((statcast_shadow.get("home") or {}).get("starter") or {}),hitters_artifact=hitters)
    return {"schema":"pulsar-v14-pitch-matchup-challenger-v1","role":ROLE,"auto_activation":False,"status":"READY_SHADOW" if home.get("status")=="READY_SHADOW" and away.get("status")=="READY_SHADOW" else "COLLECTING","home_offense":home,"away_offense":away,"head_to_head_used":False}
