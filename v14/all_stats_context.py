from __future__ import annotations

"""Bounded PIT-safe advanced-stat overlay for Pulsar V14.

This layer consumes the advanced baseball evidence already collected by V14
without using market probabilities as model features. It is deliberately a
residual layer on top of the structural/context model so team OPS, lineup OPS,
ERA/WHIP, travel, park, bullpen workload and basic weather are not counted twice.

The layer uses, when PIT-safe and available:
- lineup Statcast xwOBA, hard-hit, barrel and K-BB;
- starter arsenal x hitter pitch-type and pitcher-hand matchup;
- starter/bullpen Statcast contact/prevention quality and starter depth;
- defense/catcher/baserunning PIT artifacts when present;
- venue-relative physics weather only when its venue/month baseline is ready;
- exact timezone only as a correction to the approximate timezone already used.

Missing/unsafe components are neutral. Every component and the final team effect
are bounded. The market is never a feature.
"""

import math
from typing import Any

from .defense_baserunning_challenger import build as defense_baserunning
from .environment_physics_challenger import evaluate as environment_physics
from .pitch_matchup_challenger import build as pitch_matchup
from .starter_usage_challenger import estimate as starter_usage
from .statcast_shadow import build_shadow_features, load_priors

SCHEMA = "pulsar-v14-all-stats-context-v1"
MAX_TEAM_DELTA = 0.030
MAX_OFFENSE_DELTA = 0.018
MAX_PREVENTION_DELTA = 0.018
MAX_FIELDING_DELTA = 0.012
MAX_BASERUNNING_DELTA = 0.006
MAX_PHYSICS_DELTA = 0.004
TIMEZONE_PENALTY = -0.008


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_row(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict) or row.get("point_in_time") is not True:
        return False
    if row.get("point_in_time_validation_reasons"):
        return False
    if _mapping(row.get("data_quality")).get("eligible") is False:
        return False
    return True


def _weighted_signal(values: list[tuple[float, float, str]]) -> tuple[float | None, list[dict[str, Any]]]:
    usable = [(float(v), float(w), name) for v, w, name in values if math.isfinite(float(v)) and float(w) > 0]
    if not usable:
        return None, []
    total = sum(w for _v, w, _name in usable)
    score = sum(_clip(v, -1.5, 1.5) * w for v, w, _name in usable) / total
    return score, [{"name": name, "z": v, "weight": w} for v, w, name in usable]


def _offense_delta(lineup: dict[str, Any], matchup: dict[str, Any], running: dict[str, Any], base_mu: float) -> dict[str, Any]:
    values: list[tuple[float, float, str]] = []
    xwoba = _num(lineup.get("xwoba"))
    hard = _num(lineup.get("hard_hit_rate"))
    barrel = _num(lineup.get("barrel_rate"))
    kbb = _num(lineup.get("k_minus_bb_rate"))
    mix = _num(matchup.get("matchup_xwoba"))
    hand = _num(matchup.get("handedness_xwoba"))
    if xwoba is not None:
        values.append(((xwoba - .320) / .055, .35, "lineup_xwoba"))
    if mix is not None:
        values.append(((mix - .320) / .055, .22, "arsenal_pitch_type_matchup"))
    if hand is not None:
        values.append(((hand - .320) / .055, .08, "pitcher_hand_matchup"))
    if hard is not None:
        values.append(((hard - .38) / .08, .12, "lineup_hard_hit"))
    if barrel is not None:
        values.append(((barrel - .08) / .05, .12, "lineup_barrel"))
    if kbb is not None:
        values.append(((.12 - kbb) / .10, .11, "lineup_inverse_k_minus_bb"))
    score, components = _weighted_signal(values)
    statcast_delta = _clip((score or 0.0) * .012, -MAX_OFFENSE_DELTA, MAX_OFFENSE_DELTA) if score is not None else 0.0

    running_runs = _num(running.get("baserunning_run_adjustment")) if running.get("status") == "READY_SHADOW" else None
    running_delta = 0.0
    if running_runs is not None:
        running_delta = _clip(running_runs / max(3.5, float(base_mu)), -MAX_BASERUNNING_DELTA, MAX_BASERUNNING_DELTA)
    total = _clip(statcast_delta + running_delta, -MAX_OFFENSE_DELTA, MAX_OFFENSE_DELTA)
    return {
        "available": bool(components) or running_runs is not None,
        "score": score,
        "delta": total,
        "statcast_delta": statcast_delta,
        "baserunning_delta": running_delta,
        "components": components,
    }


def _pitcher_entity_score(row: dict[str, Any], *, include_velocity: bool) -> tuple[float | None, list[dict[str, Any]]]:
    values: list[tuple[float, float, str]] = []
    xwoba = _num(row.get("xwoba_allowed"))
    hard = _num(row.get("hard_hit_rate_allowed"))
    barrel = _num(row.get("barrel_rate_allowed"))
    kbb = _num(row.get("k_minus_bb_rate"))
    velo = _num(row.get("avg_release_speed")) if include_velocity else None
    if xwoba is not None:
        values.append(((xwoba - .320) / .055, .55, "xwoba_allowed"))
    if hard is not None:
        values.append(((hard - .38) / .08, .15, "hard_hit_allowed"))
    if barrel is not None:
        values.append(((barrel - .08) / .05, .15, "barrel_allowed"))
    if kbb is not None:
        values.append(((.12 - kbb) / .10, .10, "inverse_pitcher_k_minus_bb"))
    if velo is not None:
        values.append(((93.5 - velo) / 4.0, .05, "inverse_release_velocity"))
    return _weighted_signal(values)


def _prevention_delta(starter: dict[str, Any], bullpen: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    starter_score, starter_components = _pitcher_entity_score(starter, include_velocity=True)
    bullpen_score, bullpen_components = _pitcher_entity_score(bullpen, include_velocity=False)
    expected_ip = _num(usage.get("expected_innings"))
    if expected_ip is None:
        expected_ip = 5.2
    starter_weight = _clip(expected_ip / 9.0, .25, .80)
    scores: list[tuple[float, float, str]] = []
    if starter_score is not None:
        scores.append((starter_score, starter_weight, "starter_statcast"))
    if bullpen_score is not None:
        scores.append((bullpen_score, 1.0 - starter_weight, "bullpen_statcast"))
    combined, blend = _weighted_signal(scores)
    delta = _clip((combined or 0.0) * .012, -MAX_PREVENTION_DELTA, MAX_PREVENTION_DELTA) if combined is not None else 0.0
    return {
        "available": combined is not None,
        "score": combined,
        "delta_for_opponent_scoring": delta,
        "expected_starter_innings": expected_ip,
        "starter_components": starter_components,
        "bullpen_components": bullpen_components,
        "blend": blend,
    }


def _fielding_delta(defense: dict[str, Any]) -> dict[str, Any]:
    if defense.get("status") != "READY_SHADOW":
        return {"available": False, "delta_for_opponent_scoring": 0.0}
    df = _num(defense.get("defense_factor"))
    cf = _num(defense.get("catcher_factor"))
    if df is None and cf is None:
        return {"available": False, "delta_for_opponent_scoring": 0.0}
    combined = (df if df is not None else 1.0) * (cf if cf is not None else 1.0)
    return {
        "available": True,
        "defense_factor": df,
        "catcher_factor": cf,
        "combined_factor": combined,
        "delta_for_opponent_scoring": _clip(combined - 1.0, -MAX_FIELDING_DELTA, MAX_FIELDING_DELTA),
    }


def _timezone_residual(operational: dict[str, Any]) -> dict[str, Any]:
    exact = _num(operational.get("timezone_shift_hours_exact"))
    approx = _num(operational.get("timezone_shift_hours_approx"))
    if exact is None:
        return {"available": False, "delta": 0.0}
    exact_penalty = TIMEZONE_PENALTY if abs(exact) >= 2.0 else 0.0
    approx_penalty = TIMEZONE_PENALTY if approx is not None and abs(approx) >= 2.0 else 0.0
    return {"available": True, "exact_hours": exact, "approx_hours": approx, "delta": exact_penalty - approx_penalty}


def _physics_delta(environment: dict[str, Any]) -> dict[str, Any]:
    evidence = environment_physics(environment)
    ready = evidence.get("status") == "READY_SHADOW" and evidence.get("promotion_ready") is True
    index = _num(evidence.get("flight_environment_index")) if ready else None
    delta = _clip((index or 0.0) * MAX_PHYSICS_DELTA, -MAX_PHYSICS_DELTA, MAX_PHYSICS_DELTA)
    return {"available": index is not None, "delta": delta, "evidence": evidence}


def all_stats_overlay_from_feature_row(row: dict[str, Any] | None, home_mu: float, away_mu: float) -> dict[str, Any]:
    base_home, base_away = float(home_mu), float(away_mu)
    base = {
        "schema": SCHEMA,
        "eligible": False,
        "market_probability_used_as_feature": False,
        "home_delta": 0.0,
        "away_delta": 0.0,
        "home_mu": base_home,
        "away_mu": base_away,
        "components": {},
    }
    if not _safe_row(row):
        return {**base, "reason": "feature row not PIT-safe/eligible"}
    assert isinstance(row, dict)
    target_date = str(row.get("game_date") or "")[:10]
    if len(target_date) != 10:
        return {**base, "reason": "game_date unavailable for PIT advanced stats"}

    context = _mapping(row.get("context"))
    features = _mapping(row.get("features"))
    operational = _mapping(features.get("operational"))
    artifact = load_priors()
    statcast = build_shadow_features(row, target_date=target_date, artifact=artifact if artifact else None)
    matchup = pitch_matchup(row, statcast, artifact) if artifact else {"status": "COLLECTING"}
    defense = defense_baserunning(
        home_team_id=context.get("home_id"),
        away_team_id=context.get("away_id"),
        target_date=target_date,
    )

    home_stat = _mapping(statcast.get("home"))
    away_stat = _mapping(statcast.get("away"))
    home_usage = starter_usage(_mapping(context.get("home_starter")))
    away_usage = starter_usage(_mapping(context.get("away_starter")))
    home_defense = _mapping(defense.get("home"))
    away_defense = _mapping(defense.get("away"))

    home_offense = _offense_delta(_mapping(home_stat.get("lineup")), _mapping(matchup.get("home_offense")), home_defense, base_home)
    away_offense = _offense_delta(_mapping(away_stat.get("lineup")), _mapping(matchup.get("away_offense")), away_defense, base_away)
    home_prevention = _prevention_delta(_mapping(home_stat.get("starter")), _mapping(home_stat.get("bullpen")), home_usage)
    away_prevention = _prevention_delta(_mapping(away_stat.get("starter")), _mapping(away_stat.get("bullpen")), away_usage)
    home_fielding = _fielding_delta(home_defense)
    away_fielding = _fielding_delta(away_defense)
    home_timezone = _timezone_residual(_mapping(operational.get("home")))
    away_timezone = _timezone_residual(_mapping(operational.get("away")))
    physics = _physics_delta(_mapping(features.get("environment")))

    home_delta = _clip(
        home_offense["delta"]
        + away_prevention["delta_for_opponent_scoring"]
        + away_fielding["delta_for_opponent_scoring"]
        + home_timezone["delta"]
        + physics["delta"],
        -MAX_TEAM_DELTA,
        MAX_TEAM_DELTA,
    )
    away_delta = _clip(
        away_offense["delta"]
        + home_prevention["delta_for_opponent_scoring"]
        + home_fielding["delta_for_opponent_scoring"]
        + away_timezone["delta"]
        + physics["delta"],
        -MAX_TEAM_DELTA,
        MAX_TEAM_DELTA,
    )

    components = {
        "home_offense_statcast_matchup_baserunning": home_offense,
        "away_offense_statcast_matchup_baserunning": away_offense,
        "home_pitching_statcast_depth": home_prevention,
        "away_pitching_statcast_depth": away_prevention,
        "home_defense_catcher": home_fielding,
        "away_defense_catcher": away_fielding,
        "home_exact_timezone_residual": home_timezone,
        "away_exact_timezone_residual": away_timezone,
        "venue_relative_environment_physics": physics,
    }
    active = [name for name, component in components.items() if isinstance(component, dict) and component.get("available") is True]
    return {
        **base,
        "eligible": True,
        "home_delta": home_delta,
        "away_delta": away_delta,
        "home_mu": max(.05, base_home * (1.0 + home_delta)),
        "away_mu": max(.05, base_away * (1.0 + away_delta)),
        "caps": {
            "team": MAX_TEAM_DELTA,
            "offense": MAX_OFFENSE_DELTA,
            "prevention": MAX_PREVENTION_DELTA,
            "fielding_catcher": MAX_FIELDING_DELTA,
            "baserunning": MAX_BASERUNNING_DELTA,
            "physics": MAX_PHYSICS_DELTA,
        },
        "active_components": active,
        "statcast_artifact_schema": artifact.get("schema") if artifact else None,
        "statcast_freshness": statcast.get("freshness"),
        "pitch_matchup_status": matchup.get("status"),
        "defense_baserunning_status": defense.get("status"),
        "double_count_policy": "advanced residuals only; structural/context stats are not re-used",
        "components": components,
    }
