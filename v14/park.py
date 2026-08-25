from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PARK_MANIFEST = Path("data/v14_park_factors_manifest.json")
EXPECTED_MANIFEST_SCHEMA = "pulsar-v14-park-factor-manifest-v1"


def _num(value: Any, default: float | None=None) -> float | None:
    try:
        out=float(value); return out if math.isfinite(out) else default
    except Exception: return default


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def load(manifest_path: Path=PARK_MANIFEST) -> dict[str,Any]:
    """Load frozen historical park evidence through a V14-native manifest."""
    if not manifest_path.exists(): return {}
    try: manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:return {}
    if manifest.get("schema")!=EXPECTED_MANIFEST_SCHEMA:return {}
    source=Path(str(manifest.get("source_path") or "")); expected=str(manifest.get("source_schema") or "")
    if not source.exists() or not expected:return {}
    try: payload=json.loads(source.read_text(encoding="utf-8"))
    except Exception:return {}
    if payload.get("schema")!=expected:return {}
    return payload


def venue_prior(artifact:dict[str,Any],target_season:int,venue:str)->dict[str,Any]:
    sides=(((artifact or {}).get("seasons") or {}).get(str(int(target_season))) or {}); out={"available":False,"target_season":int(target_season),"venue":str(venue or ""),"point_in_time":True,"provider":"Baseball Savant / MLB Stats prior park factor"}; key=_norm(venue)
    for side in ("ALL","L","R"):
        payload=sides.get(side) or {}; row=next((r for r in payload.get("rows") or [] if _norm(r.get("venue"))==key),None)
        if row:
            out[side.lower()]=row; out["source_window_end_season"]=payload.get("source_window_end_season"); out["source_window_years"]=payload.get("source_window_years"); out["savant_rolling_seasons"]=payload.get("savant_rolling_seasons"); out["provider_fallback"]=bool(payload.get("provider_fallback")); out["handedness_specific"]=bool(payload.get("handedness_specific"))
    out["available"]=any(k in out for k in ("all","l","r")); return out


def resolve(*,target_season:int,venue:str,static_factor:float,artifact:dict[str,Any]|None=None)->dict[str,Any]:
    static=float(_num(static_factor,1.0) or 1.0); base={"schema":"v14-runtime-park-factor-v2","active":False,"factor":static,"static_factor":static,"target_season":int(target_season),"venue":str(venue or "") or None,"leakage_safe":True,"source":"static park fallback supplied by V14 data contract"}
    if not venue:return {**base,"reason":"venue_missing"}
    prior=venue_prior(load() if artifact is None else artifact,int(target_season),venue)
    if not prior.get("available"):return {**base,"reason":"prior_venue_missing"}
    source_end=prior.get("source_window_end_season")
    if source_end is None or int(source_end)!=int(target_season)-1:return {**base,"reason":"prior_window_not_strictly_previous"}
    row=prior.get("all") or {}; index=_num(row.get("runs_index")); metric="runs_index"
    if index is None:index=_num(row.get("park_factor_index")); metric="park_factor_index"
    if index is None:return {**base,"reason":"prior_factor_missing"}
    factor=index/100.0
    if not .75<=factor<=1.35:return {**base,"reason":"prior_factor_out_of_bounds"}
    return {**base,"active":True,"factor":factor,"index":index,"metric":metric,"source":str(row.get("source_method") or prior.get("provider") or "prior park factor"),"provider_fallback":bool(prior.get("provider_fallback")),"source_window_end_season":int(source_end),"handedness_specific":False,"reason":"validated_prior_venue_factor"}


def apply(home_mu:float,away_mu:float,*,target_season:int,venue:str,static_factor:float,artifact:dict[str,Any]|None=None)->tuple[float,float,dict[str,Any]]:
    meta=resolve(target_season=target_season,venue=venue,static_factor=static_factor,artifact=artifact); static=max(.5,min(1.5,float(meta.get("static_factor") or 1))); factor=max(.5,min(1.5,float(meta.get("factor") or static))); ratio=factor/static if static>0 else 1.0; meta["correction_ratio_vs_static"]=ratio
    if not meta.get("active"):return float(home_mu),float(away_mu),meta
    return max(.2,float(home_mu)*ratio),max(.2,float(away_mu)*ratio),meta
