from __future__ import annotations

"""Prospective raw-probability ablations for the frozen V14 champion.

Ablations are shadow-only counterfactuals generated from already-computed
point-in-time champion components. They never feed production decisions and
never use market probabilities.

The scorer intentionally works on the uncalibrated probability surface. That
keeps reconstruction independent from any calibrator learned after the original
pregame snapshot. Before an ablation is accepted, the module reconstructs the
FULL raw champion surface and requires numerical parity with the raw surface
persisted at prediction time. If any frozen distribution input has drifted, the
row fails closed instead of being retrospectively rewritten.
"""

from typing import Any

from .all_stats_context import MAX_TEAM_DELTA as MAX_ADVANCED_TEAM_DELTA
from .champion_contract import (
    CHAMPION_DISPERSION,
    CHAMPION_ENVIRONMENT_SIGMA,
    validated_extra_innings_home_probability,
)
from .context_overlay import MAX_TEAM_DELTA as MAX_CONTEXT_TEAM_DELTA
from .distribution import probability_surface
from .model import RunProjection

RAW_PARITY_TOLERANCE = 1e-9
PROBABILITY_KEYS = (
    "home_ml",
    "away_ml",
    "home_minus_1_5",
    "away_plus_1_5",
    "away_minus_1_5",
    "home_plus_1_5",
    "over",
    "under",
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clip(value: float, limit: float) -> float:
    return max(-float(limit), min(float(limit), float(value)))


def _component_delta(component: Any, *keys: str) -> float:
    if not isinstance(component, dict):
        return 0.0
    for key in keys:
        if key in component:
            return _num(component.get(key), 0.0)
    return 0.0


def _surface_raw(prediction: dict[str, Any], home_mu: float, away_mu: float) -> dict[str, Any]:
    run = prediction.get("run_projection") or {}
    projection = RunProjection(
        game_pk=str(prediction.get("game_pk") or ""),
        game_date=str(prediction.get("game_date") or ""),
        analyzed_at=str(prediction.get("analyzed_at") or ""),
        home=str(prediction.get("home") or ""),
        away=str(prediction.get("away") or ""),
        home_mu=max(0.05, float(home_mu)),
        away_mu=max(0.05, float(away_mu)),
        total_line=float(prediction.get("total_line")),
        phase=str(prediction.get("phase") or "EARLY"),
        dispersion=float(run.get("dispersion")),
        environment_sigma=float(run.get("environment_sigma")),
        extra_innings_home_probability=float(run.get("extra_innings_home_probability")),
        source_generation=str(prediction.get("model_generation") or ""),
    ).validated()
    raw, tail = probability_surface(projection)
    return {
        "home_mu": projection.home_mu,
        "away_mu": projection.away_mu,
        "raw_probabilities": raw.as_dict(),
        "tail_mass": tail,
    }


def _max_probability_delta(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    deltas: list[float] = []
    for key in PROBABILITY_KEYS:
        if left.get(key) is None or right.get(key) is None:
            return None
        deltas.append(abs(float(left[key]) - float(right[key])))
    return max(deltas) if deltas else None


def _context_components(prediction: dict[str, Any]) -> dict[str, Any]:
    return (prediction.get("context_adjustment") or {}).get("components") or {}


def _advanced_components(prediction: dict[str, Any]) -> dict[str, Any]:
    return (prediction.get("advanced_stats_adjustment") or {}).get("components") or {}


def _context_delta_without(prediction: dict[str, Any], excluded: set[str]) -> tuple[float, float]:
    components = _context_components(prediction)
    home_parts = {
        "STARTER": _component_delta(components.get("home_offense_vs_away_starter_residual"), "delta"),
        "LINEUP": _component_delta(components.get("home_lineup_residual"), "delta"),
        "BULLPEN": _component_delta(components.get("away_bullpen_three_day_for_home"), "delta"),
        "WEATHER": _component_delta(components.get("shared_environment"), "delta"),
    }
    away_parts = {
        "STARTER": _component_delta(components.get("away_offense_vs_home_starter_residual"), "delta"),
        "LINEUP": _component_delta(components.get("away_lineup_residual"), "delta"),
        "BULLPEN": _component_delta(components.get("home_bullpen_three_day_for_away"), "delta"),
        "WEATHER": _component_delta(components.get("shared_environment"), "delta"),
    }
    home = _clip(sum(v for k, v in home_parts.items() if k not in excluded), MAX_CONTEXT_TEAM_DELTA)
    away = _clip(sum(v for k, v in away_parts.items() if k not in excluded), MAX_CONTEXT_TEAM_DELTA)
    return home, away


def _advanced_delta_without(prediction: dict[str, Any], excluded: set[str]) -> tuple[float, float]:
    c = _advanced_components(prediction)
    home_parts = {
        "STATCAST": _component_delta(c.get("home_offense_statcast_matchup_baserunning"), "delta")
        + _component_delta(c.get("away_pitching_statcast_depth"), "delta_for_opponent_scoring"),
        "DEFENSE": _component_delta(c.get("away_defense_catcher"), "delta_for_opponent_scoring"),
        "TIMEZONE": _component_delta(c.get("home_exact_timezone_residual"), "delta"),
        "PHYSICS": _component_delta(c.get("venue_relative_environment_physics"), "delta"),
    }
    away_parts = {
        "STATCAST": _component_delta(c.get("away_offense_statcast_matchup_baserunning"), "delta")
        + _component_delta(c.get("home_pitching_statcast_depth"), "delta_for_opponent_scoring"),
        "DEFENSE": _component_delta(c.get("home_defense_catcher"), "delta_for_opponent_scoring"),
        "TIMEZONE": _component_delta(c.get("away_exact_timezone_residual"), "delta"),
        "PHYSICS": _component_delta(c.get("venue_relative_environment_physics"), "delta"),
    }
    home = _clip(sum(v for k, v in home_parts.items() if k not in excluded), MAX_ADVANCED_TEAM_DELTA)
    away = _clip(sum(v for k, v in away_parts.items() if k not in excluded), MAX_ADVANCED_TEAM_DELTA)
    return home, away


def _means(
    base_home: float,
    base_away: float,
    context_delta: tuple[float, float],
    advanced_delta: tuple[float, float],
) -> tuple[float, float]:
    contextual_home = max(0.05, base_home * (1.0 + context_delta[0]))
    contextual_away = max(0.05, base_away * (1.0 + context_delta[1]))
    return (
        max(0.05, contextual_home * (1.0 + advanced_delta[0])),
        max(0.05, contextual_away * (1.0 + advanced_delta[1])),
    )


def build(prediction: dict[str, Any]) -> dict[str, Any]:
    base = prediction.get("base_run_projection") or {}
    base_home = _num(base.get("home_mu"), -1.0)
    base_away = _num(base.get("away_mu"), -1.0)
    if base_home <= 0 or base_away <= 0:
        return {
            "schema": "pulsar-v14-ablation-shadow-v2",
            "role": "SHADOW_ONLY",
            "champion_impact": False,
            "status": "UNAVAILABLE",
            "reason": "base_run_projection unavailable",
            "variants": {},
        }

    context = prediction.get("context_adjustment") or {}
    advanced = prediction.get("advanced_stats_adjustment") or {}
    full_context = (_num(context.get("home_delta")), _num(context.get("away_delta")))
    full_advanced = (_num(advanced.get("home_delta")), _num(advanced.get("away_delta")))

    full_home, full_away = _means(base_home, base_away, full_context, full_advanced)
    reconstructed = _surface_raw(prediction, full_home, full_away)
    persisted_raw = prediction.get("raw_probabilities") or {}
    parity_delta = _max_probability_delta(
        reconstructed.get("raw_probabilities") or {},
        persisted_raw if isinstance(persisted_raw, dict) else {},
    )
    if parity_delta is None or parity_delta > RAW_PARITY_TOLERANCE:
        return {
            "schema": "pulsar-v14-ablation-shadow-v2",
            "role": "SHADOW_ONLY",
            "champion_impact": False,
            "status": "UNAVAILABLE",
            "reason": "full_raw_reconstruction_mismatch",
            "raw_reconstruction_max_abs_delta": parity_delta,
            "raw_parity_tolerance": RAW_PARITY_TOLERANCE,
            "variants": {},
            "interpretation": (
                "The historical row cannot be reconstructed under today's frozen distribution inputs "
                "with exact raw-probability parity, so it is excluded rather than backfilled."
            ),
        }

    configs: dict[str, tuple[tuple[float, float], tuple[float, float], str]] = {
        "STRUCTURAL_ONLY": ((0.0, 0.0), (0.0, 0.0), "remove context and advanced residual layers"),
        "NO_ADVANCED_STATS": (full_context, (0.0, 0.0), "remove entire advanced all-stats layer"),
        "NO_CONTEXT_RESIDUAL": ((0.0, 0.0), full_advanced, "remove context layer while freezing advanced residual delta"),
    }

    for label, group in (
        ("NO_STARTER_RESIDUAL", "STARTER"),
        ("NO_LINEUP_RESIDUAL", "LINEUP"),
        ("NO_BULLPEN_RESIDUAL", "BULLPEN"),
        ("NO_WEATHER_CONTEXT", "WEATHER"),
    ):
        configs[label] = (
            _context_delta_without(prediction, {group}),
            full_advanced,
            f"remove {group.lower()} context residual; other deltas frozen",
        )

    for label, group in (
        ("NO_ADVANCED_STATCAST", "STATCAST"),
        ("NO_ADVANCED_DEFENSE", "DEFENSE"),
        ("NO_ADVANCED_TIMEZONE", "TIMEZONE"),
        ("NO_ADVANCED_PHYSICS", "PHYSICS"),
    ):
        configs[label] = (
            full_context,
            _advanced_delta_without(prediction, {group}),
            f"remove {group.lower()} advanced residual; other deltas frozen",
        )

    variants: dict[str, Any] = {}
    for name, (ctx_delta, adv_delta, note) in configs.items():
        home_mu, away_mu = _means(base_home, base_away, ctx_delta, adv_delta)
        variants[name] = {
            **_surface_raw(prediction, home_mu, away_mu),
            "role": "SHADOW_ONLY",
            "champion_impact": False,
            "market_probability_used_as_feature": False,
            "context_delta": {"home": ctx_delta[0], "away": ctx_delta[1]},
            "advanced_delta": {"home": adv_delta[0], "away": adv_delta[1]},
            "counterfactual_note": note,
        }

    return {
        "schema": "pulsar-v14-ablation-shadow-v2",
        "role": "SHADOW_ONLY",
        "champion_impact": False,
        "status": "READY",
        "market_probability_used_as_feature": False,
        "score_contract": "RAW_UNCALIBRATED_PROBABILITY_SURFACE",
        "raw_reconstruction_max_abs_delta": parity_delta,
        "raw_parity_tolerance": RAW_PARITY_TOLERANCE,
        "reference_raw_probabilities": dict(persisted_raw),
        "variants": variants,
        "method": (
            "prospective component-freeze counterfactuals from persisted PIT champion run deltas; "
            "full raw champion parity required before scoring; no market data, no post-hoc calibrator, "
            "and no production activation"
        ),
    }


def build_from_tracking_row(row: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct fail-closed raw ablations from immutable pregame tracking features.

    Outcome fields are never read. The current frozen distribution inputs are used
    only as a reconstruction candidate; exact parity against the persisted raw
    champion surface is mandatory, so drift causes exclusion instead of leakage.
    """
    training = row.get("training_features") or {}
    extra, _meta = validated_extra_innings_home_probability()
    prediction = {
        "game_pk": row.get("game_pk"),
        "game_date": row.get("game_date"),
        "analyzed_at": row.get("analyzed_at"),
        "home": row.get("home"),
        "away": row.get("away"),
        "phase": row.get("phase"),
        "model_generation": row.get("model_generation"),
        "total_line": row.get("total_line"),
        "run_projection": {
            "home_mu": row.get("home_mu"),
            "away_mu": row.get("away_mu"),
            "dispersion": CHAMPION_DISPERSION,
            "environment_sigma": CHAMPION_ENVIRONMENT_SIGMA,
            "extra_innings_home_probability": extra,
        },
        "base_run_projection": training.get("base_run_projection") or {},
        "context_adjustment": training.get("context_adjustment") or {},
        "advanced_stats_adjustment": training.get("advanced_stats_adjustment") or {},
        "raw_probabilities": row.get("raw_probabilities") or {},
    }
    return build(prediction)
