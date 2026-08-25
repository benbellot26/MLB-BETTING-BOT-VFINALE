from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PARK_ARTIFACT = Path("data/v137_park_factors.json")
EXPECTED_SCHEMA = "v13-7-prior-park-factors-store-v5"


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def load(path: Path = PARK_ARTIFACT) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if payload.get("schema") == EXPECTED_SCHEMA else {}


def venue_prior(artifact: dict[str, Any], target_season: int, venue: str) -> dict[str, Any]:
    sides = (((artifact or {}).get("seasons") or {}).get(str(int(target_season))) or {})
    out: dict[str, Any] = {
        "available": False,
        "target_season": int(target_season),
        "venue": str(venue or ""),
        "point_in_time": True,
        "provider": "Baseball Savant / MLB Stats prior park factor",
    }
    key = _norm(venue)
    for side in ("ALL", "L", "R"):
        payload = sides.get(side) or {}
        row = next((row for row in payload.get("rows") or [] if _norm(row.get("venue")) == key), None)
        if row:
            out[side.lower()] = row
            out["source_window_end_season"] = payload.get("source_window_end_season")
            out["source_window_years"] = payload.get("source_window_years")
            out["savant_rolling_seasons"] = payload.get("savant_rolling_seasons")
            out["provider_fallback"] = bool(payload.get("provider_fallback"))
            out["handedness_specific"] = bool(payload.get("handedness_specific"))
    out["available"] = any(key in out for key in ("all", "l", "r"))
    return out


def resolve(*, target_season: int, venue: str, static_factor: float,
            artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Native V14 port of the active V13.10 leakage-safe park contract."""
    static = float(_num(static_factor, 1.0) or 1.0)
    base = {
        "schema": "v14-runtime-park-factor-v1",
        "active": False,
        "factor": static,
        "static_factor": static,
        "target_season": int(target_season),
        "venue": str(venue or "") or None,
        "leakage_safe": True,
        "source": "static park fallback supplied by V14 data contract",
    }
    if not venue:
        return {**base, "reason": "venue_missing"}
    prior = venue_prior(load() if artifact is None else artifact, int(target_season), venue)
    if not prior.get("available"):
        return {**base, "reason": "prior_venue_missing"}
    source_end = prior.get("source_window_end_season")
    if source_end is None or int(source_end) != int(target_season) - 1:
        return {**base, "reason": "prior_window_not_strictly_previous"}
    row = prior.get("all") or {}
    index = _num(row.get("runs_index"))
    metric = "runs_index"
    if index is None:
        index = _num(row.get("park_factor_index"))
        metric = "park_factor_index"
    if index is None:
        return {**base, "reason": "prior_factor_missing"}
    factor = index / 100.0
    if not 0.75 <= factor <= 1.35:
        return {**base, "reason": "prior_factor_out_of_bounds"}
    return {
        **base,
        "active": True,
        "factor": factor,
        "index": index,
        "metric": metric,
        "source": str(row.get("source_method") or prior.get("provider") or "prior park factor"),
        "provider_fallback": bool(prior.get("provider_fallback")),
        "source_window_end_season": int(source_end),
        "handedness_specific": False,
        "reason": "validated_prior_venue_factor",
    }


def apply(home_mu: float, away_mu: float, *, target_season: int, venue: str,
          static_factor: float, artifact: dict[str, Any] | None = None) -> tuple[float, float, dict[str, Any]]:
    meta = resolve(
        target_season=target_season,
        venue=venue,
        static_factor=static_factor,
        artifact=artifact,
    )
    static = max(0.5, min(1.5, float(meta.get("static_factor") or 1.0)))
    factor = max(0.5, min(1.5, float(meta.get("factor") or static)))
    ratio = factor / static if static > 0 else 1.0
    meta["correction_ratio_vs_static"] = ratio
    if not meta.get("active"):
        return float(home_mu), float(away_mu), meta
    return max(0.2, float(home_mu) * ratio), max(0.2, float(away_mu) * ratio), meta
