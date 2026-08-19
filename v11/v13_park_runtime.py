from __future__ import annotations

import math
import os
from typing import Any

from . import core
from . import v137_park_factors as park


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _enabled() -> bool:
    return str(os.getenv("V13_ENABLE_PRIOR_PARK_RUNTIME", "1")).lower() in {"1", "true", "yes"}


def _venue_name(result: dict[str, Any]) -> str:
    game = result.get("game") or {}
    return str((game.get("venue") or {}).get("name") or "").strip()


def resolve(result: dict[str, Any], target_season: int | None = None) -> dict[str, Any]:
    """Resolve a run park factor from leakage-safe completed-season evidence.

    Only the ALL-side prior is allowed to move the structural run environment.
    Handedness-specific rows remain available to research modules but are not
    mixed into the champion until separately validated. If the exact venue is
    absent or the prior window is not strictly prior to the target season, the
    established static factor remains the fail-closed fallback.
    """
    ctx = result.get("ctx") or {}
    home = str(ctx.get("home") or "")
    season = int(target_season or core.SEASON)
    static_factor = float(core.PARK.get(home, 1.0))
    base = {
        "schema": "v13-runtime-park-factor-v1",
        "active": False,
        "factor": static_factor,
        "static_factor": static_factor,
        "source": "core.PARK static fallback",
        "target_season": season,
        "venue": _venue_name(result) or None,
        "leakage_safe": True,
    }
    if not _enabled():
        base["reason"] = "runtime_prior_disabled"
        return base
    venue = _venue_name(result)
    if not venue:
        base["reason"] = "venue_missing"
        return base
    artifact = park.load()
    prior = park.venue_prior(artifact, season, venue)
    if not prior.get("available"):
        base["reason"] = "prior_venue_missing"
        return base
    source_end = prior.get("source_window_end_season")
    if source_end is None or int(source_end) != season - 1:
        base["reason"] = "prior_window_not_strictly_previous"
        return base
    row = prior.get("all") or {}
    index = _num(row.get("runs_index"))
    metric = "runs_index"
    if index is None:
        index = _num(row.get("park_factor_index"))
        metric = "park_factor_index"
    if index is None:
        base["reason"] = "prior_factor_missing"
        return base
    factor = index / 100.0
    if not .75 <= factor <= 1.35:
        base["reason"] = "prior_factor_out_of_bounds"
        return base
    base.update({
        "active": True,
        "factor": factor,
        "index": index,
        "metric": metric,
        "source": str(row.get("source_method") or prior.get("provider") or "prior park factor"),
        "provider_fallback": bool(prior.get("provider_fallback")),
        "source_window_end_season": int(source_end),
        "handedness_specific": False,
        "reason": "validated_prior_venue_factor",
    })
    return base


def apply(result: dict[str, Any], structural_home_mu: float, structural_away_mu: float) -> tuple[float, float, dict[str, Any]]:
    meta = resolve(result)
    static = max(.5, min(1.5, float(meta.get("static_factor") or 1.0)))
    factor = max(.5, min(1.5, float(meta.get("factor") or static)))
    ratio = factor / static if static > 0 else 1.0
    meta["correction_ratio_vs_static"] = ratio
    if not meta.get("active"):
        return float(structural_home_mu), float(structural_away_mu), meta
    return (
        max(.2, float(structural_home_mu) * ratio),
        max(.2, float(structural_away_mu) * ratio),
        meta,
    )
