from __future__ import annotations

"""Leakage-safe Statcast shadow features for V14.

The existing v13.7 ID-first Statcast artifact is reused only when its cutoff is
not later than the target game date. These features are persisted for challenger
training and diagnostics; they do not alter champion probabilities directly.
"""

from datetime import date
import gzip
import json
import math
from pathlib import Path
from typing import Any

STATCAST_PRIORS = Path("data/v137_statcast_priors_latest.json.gz")
EXPECTED_SCHEMA = "v13-7-statcast-id-priors-v1"
MIN_HITTER_PA = 30
MIN_PITCHER_PA = 60


def _num(value: Any) -> float | None:
    try:
        out=float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def load_priors(path: Path | str = STATCAST_PRIORS) -> dict[str, Any]:
    target=Path(path)
    if not target.exists(): return {}
    try:
        with gzip.open(target,"rt",encoding="utf-8") as fh: payload=json.load(fh)
    except Exception: return {}
    if not isinstance(payload,dict) or payload.get("schema")!=EXPECTED_SCHEMA or payload.get("point_in_time") is not True or payload.get("stable_id_only") is not True: return {}
    return payload


def _artifact_safe(payload: dict[str, Any], target_date: str) -> tuple[bool,str]:
    try:
        target=date.fromisoformat(str(target_date)[:10]); cutoff=date.fromisoformat(str(payload.get("cutoff_day")))
    except Exception:
        return False,"invalid_cutoff_or_target_date"
    # Artifact contains only pitches strictly before cutoff_day. A cutoff equal
    # to target date is ideal; an older cutoff is safe but less fresh.
    if cutoff>target: return False,"artifact_cutoff_after_target"
    return True,"safe_prior_cutoff"


def _weighted_mean(rows: list[tuple[float,float]]) -> float | None:
    total=sum(w for _v,w in rows)
    return sum(v*w for v,w in rows)/total if total>0 else None


def _lineup_feature(lineup: dict[str, Any], hitters: dict[str, Any]) -> dict[str, Any]:
    weights=(1.04,1.05,1.08,1.10,1.06,1.00,.96,.93,.90); covered=[]; xw=[]; hard=[]; barrel=[]; kbb=[]
    for i,player in enumerate((lineup.get("players") or [])[:9]):
        pid=str(player.get("id") or "")
        prior=hitters.get(pid) or {}; pa=int(_num(prior.get("pa")) or 0)
        if not pid or pa<MIN_HITTER_PA: continue
        w=weights[min(i,8)]*min(1.0,pa/120.0); covered.append({"id":pid,"pa":pa})
        for bucket,key in ((xw,"xwoba"),(hard,"hard_hit_rate"),(barrel,"barrel_rate"),(kbb,"k_minus_bb_rate")):
            value=_num(prior.get(key))
            if value is not None: bucket.append((value,w))
    return {
        "status":"READY" if len(covered)>=5 else "INSUFFICIENT_COVERAGE",
        "coverage":len(covered)/9.0,
        "covered_hitters":len(covered),
        "xwoba":_weighted_mean(xw),
        "hard_hit_rate":_weighted_mean(hard),
        "barrel_rate":_weighted_mean(barrel),
        "k_minus_bb_rate":_weighted_mean(kbb),
        "players":covered,
    }


def _starter_feature(starter: dict[str, Any], pitchers: dict[str, Any]) -> dict[str, Any]:
    pid=str(starter.get("id") or ""); prior=pitchers.get(pid) or {}; pa=int(_num(prior.get("pa")) or 0)
    if not pid or pa<MIN_PITCHER_PA: return {"status":"INSUFFICIENT_COVERAGE","id":pid or None,"pa":pa}
    return {
        "status":"READY","id":pid,"pa":pa,
        "xwoba_allowed":_num(prior.get("xwoba")),
        "hard_hit_rate_allowed":_num(prior.get("hard_hit_rate")),
        "barrel_rate_allowed":_num(prior.get("barrel_rate")),
        "k_minus_bb_rate":_num(prior.get("k_minus_bb_rate")),
        "avg_release_speed":_num(prior.get("avg_release_speed")),
        "pitch_mix":prior.get("pitch_mix") or {},
        "max_game_date":prior.get("max_game_date"),
    }


def _bullpen_feature(snapshot: dict[str, Any], pitchers: dict[str, Any]) -> dict[str, Any]:
    rows=[]; xw=[]; hard=[]; barrel=[]; kbb=[]
    for reliever in snapshot.get("relievers") or []:
        if reliever.get("likely_unavailable") is True or reliever.get("available") is False: continue
        pid=str(reliever.get("id") or ""); prior=pitchers.get(pid) or {}; pa=int(_num(prior.get("pa")) or 0)
        if not pid or pa<MIN_PITCHER_PA: continue
        # Higher recent workload reduces expected availability weight, but never
        # deletes a pitcher solely because of a heuristic workload threshold.
        pitches=float(_num(reliever.get("pitches_last_3d")) or 0.0); w=min(1.0,pa/120.0)*max(.25,1.0-min(.65,pitches/100.0)); rows.append({"id":pid,"pa":pa,"weight":w})
        for bucket,key in ((xw,"xwoba"),(hard,"hard_hit_rate"),(barrel,"barrel_rate"),(kbb,"k_minus_bb_rate")):
            value=_num(prior.get(key))
            if value is not None: bucket.append((value,w))
    return {
        "status":"READY" if len(rows)>=3 else "INSUFFICIENT_COVERAGE",
        "covered_available_relievers":len(rows),
        "xwoba_allowed":_weighted_mean(xw),
        "hard_hit_rate_allowed":_weighted_mean(hard),
        "barrel_rate_allowed":_weighted_mean(barrel),
        "k_minus_bb_rate":_weighted_mean(kbb),
        "relievers":rows,
    }


def build_shadow_features(feature_row: dict[str, Any], *, target_date: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    priors=load_priors() if artifact is None else artifact; safe,reason=_artifact_safe(priors,target_date) if priors else (False,"artifact_unavailable")
    base={"schema":"pulsar-v14-statcast-shadow-v1","role":"SHADOW_ONLY","auto_activation":False,"point_in_time":safe,"target_date":str(target_date),"artifact_cutoff_day":priors.get("cutoff_day") if priors else None,"reason":reason}
    if not safe: return base
    ctx=feature_row.get("context") or {}; features=feature_row.get("features") or {}; hitters=priors.get("hitters") or {}; pitchers=priors.get("pitchers") or {}
    return {**base,
        "home":{"lineup":_lineup_feature(ctx.get("home_lineup") or {},hitters),"starter":_starter_feature(ctx.get("home_starter") or {},pitchers),"bullpen":_bullpen_feature(((features.get("bullpen") or {}).get("home") or {}),pitchers)},
        "away":{"lineup":_lineup_feature(ctx.get("away_lineup") or {},hitters),"starter":_starter_feature(ctx.get("away_starter") or {},pitchers),"bullpen":_bullpen_feature(((features.get("bullpen") or {}).get("away") or {}),pitchers)},
    }
