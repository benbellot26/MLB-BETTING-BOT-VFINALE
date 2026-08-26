from __future__ import annotations

"""Venue-keyed park-factor research layer.

Park effects belong to a venue, not to the franchise occupying it. The active
champion remains unchanged until OOS validation. A transformed source may be
usable as shadow evidence without automatically becoming promotion-eligible.
"""

from datetime import date
import json
import math
from pathlib import Path
from typing import Any

ROLE="CHALLENGER_ONLY"
ARTIFACT=Path("data/v14_venue_park_factors.json")


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def load(path:Path|str=ARTIFACT)->dict[str,Any]:
    target=Path(path)
    if not target.exists(): return {}
    try: payload=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {}
    return payload if isinstance(payload,dict) and payload.get("point_in_time") is True else {}


def _safe(payload:dict[str,Any],target_date:str)->bool:
    try: return date.fromisoformat(str(payload.get("cutoff_day")))<date.fromisoformat(str(target_date)[:10])
    except Exception: return False


def resolve(*,venue_id:Any,venue_name:Any,target_date:str,legacy_team_factor:float|None=None,artifact:dict[str,Any]|None=None)->dict[str,Any]:
    payload=load() if artifact is None else artifact; base={"schema":"pulsar-v14-venue-park-challenger-v2","role":ROLE,"auto_activation":False,"venue_id":str(venue_id) if venue_id is not None else None,"venue_name":str(venue_name or ""),"target_date":str(target_date),"market_probability_used_as_feature":False}
    if payload and _safe(payload,target_date):
        venues=payload.get("venues") or {}; row=venues.get(str(venue_id)) or venues.get(str(venue_name)) or {}; factor=_num(row.get("factor") or row.get("run_factor") or row.get("index"))
        if factor is not None and .75<=factor<=1.30:
            promotion_ready=bool(payload.get("promotion_eligible") is True and row.get("promotion_eligible") is True)
            return {**base,"status":"READY_SHADOW","factor":factor,"handedness":row.get("handedness") or {},"components":row.get("components") or {},"source":"venue PIT artifact","source_method":row.get("source_method"),"cutoff_day":payload.get("cutoff_day"),"source_window_end_season":payload.get("source_window_end_season"),"promotion_ready":promotion_ready,"promotion_blocker":None if promotion_ready else "source artifact is shadow-valid but not promotion-eligible"}
    fallback=_num(legacy_team_factor)
    return {**base,"status":"COLLECTING","factor":fallback,"source":"legacy team-keyed fallback" if fallback is not None else None,"promotion_ready":False,"reason":"venue-level PIT factor unavailable or unsafe; fallback cannot be promoted"}
