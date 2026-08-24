from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

MAX_OPERATIONAL_RUN_ADJ = 0.05
MIN_STRUCTURAL_MU = 1.8
MAX_STRUCTURAL_MU = 7.5


@dataclass(frozen=True)
class LeagueBaselines:
    rpg: float = 4.45
    ops: float = 0.710
    era: float = 4.35
    whip: float = 1.32


@dataclass(frozen=True)
class Starter:
    era: float
    whip: float
    k9: float | None = None
    bb9: float | None = None
    hr9: float | None = None
    innings: float = 0.0
    sample_weight: float = 0.0


@dataclass(frozen=True)
class TeamInputs:
    runs_per_game: float
    ops: float
    lineup_ops: float
    team_era: float
    starter: Starter
    enhanced_starter: Starter
    operational: dict[str, Any]


@dataclass(frozen=True)
class StructuralInputs:
    league: LeagueBaselines
    home: TeamInputs
    away: TeamInputs
    static_park_factor: float
    current_doubleheader: bool = False


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def ratio(value: float, baseline: float, low: float = 0.75, high: float = 1.28) -> float:
    return _clamp(_num(value, baseline) / max(1e-9, _num(baseline, 1.0)), low, high)


def starter_quality(starter: Starter, league: LeagueBaselines) -> float:
    return 0.68 * ratio(starter.era, league.era) + 0.32 * ratio(starter.whip, league.whip)


def offense_factor(team: TeamInputs, league: LeagueBaselines) -> float:
    return (
        0.42 * ratio(team.runs_per_game, league.rpg)
        + 0.33 * ratio(team.ops, league.ops)
        + 0.25 * ratio(team.lineup_ops, league.ops)
    )


def opponent_factor(opponent_team_era: float, opponent_starter: Starter, league: LeagueBaselines) -> float:
    return 0.52 * ratio(opponent_team_era, league.era) + 0.48 * starter_quality(opponent_starter, league)


def fatigue_adjustment(operational: dict[str, Any]) -> float:
    adj = 0.0
    distance = _num(operational.get("travel_km"), 0.0)
    timezone_shift = abs(_num(operational.get("timezone_shift_hours_approx"), 0.0))
    if distance >= 1500:
        adj -= 0.012
    if distance >= 3000:
        adj -= 0.008
    if timezone_shift >= 2:
        adj -= 0.008
    if operational.get("previous_extra_innings"):
        adj -= 0.010
    if operational.get("previous_doubleheader"):
        adj -= 0.008
    rest_days = operational.get("rest_days")
    if rest_days is not None and _num(rest_days) >= 1:
        adj += 0.006
    return adj


def bullpen_attack_adjustment(opponent_operational: dict[str, Any]) -> float:
    bullpen = (opponent_operational.get("bullpen_previous_game") or {})
    return min(
        0.035,
        0.00022 * _num(bullpen.get("relief_pitches"), 0.0)
        + 0.006 * _num(bullpen.get("heavy_relievers"), 0.0),
    )


def operational_adjustments(inputs: StructuralInputs) -> tuple[float, float]:
    home_adj = _clamp(
        fatigue_adjustment(inputs.home.operational) + bullpen_attack_adjustment(inputs.away.operational),
        -MAX_OPERATIONAL_RUN_ADJ,
        MAX_OPERATIONAL_RUN_ADJ,
    )
    away_adj = _clamp(
        fatigue_adjustment(inputs.away.operational) + bullpen_attack_adjustment(inputs.home.operational),
        -MAX_OPERATIONAL_RUN_ADJ,
        MAX_OPERATIONAL_RUN_ADJ,
    )
    # V13 applies the current-doubleheader penalty after the ±0.05 clamp.
    if inputs.current_doubleheader:
        home_adj -= 0.004
        away_adj -= 0.004
    return home_adj, away_adj


def legacy_structural_projection(inputs: StructuralInputs) -> dict[str, Any]:
    """Native port of the V13.10 underlying structural projection math."""
    league = inputs.league
    home_offense = offense_factor(inputs.home, league)
    away_offense = offense_factor(inputs.away, league)
    home_opponent = opponent_factor(inputs.away.team_era, inputs.away.starter, league)
    away_opponent = opponent_factor(inputs.home.team_era, inputs.home.starter, league)
    park = _num(inputs.static_park_factor, 1.0)

    home_mu = league.rpg * home_offense * home_opponent * park * 1.025
    away_mu = league.rpg * away_offense * away_opponent * park * 0.975
    home_adj, away_adj = operational_adjustments(inputs)
    home_mu = _clamp(home_mu * (1.0 + home_adj), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    away_mu = _clamp(away_mu * (1.0 + away_adj), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    return {
        "home_mu": home_mu,
        "away_mu": away_mu,
        "home_offense_factor": home_offense,
        "away_offense_factor": away_offense,
        "home_opponent_factor": home_opponent,
        "away_opponent_factor": away_opponent,
        "home_operational_adjustment": home_adj,
        "away_operational_adjustment": away_adj,
        "static_park_factor": park,
    }


def rescale_for_enhanced_starters(home_mu: float, away_mu: float, inputs: StructuralInputs) -> dict[str, Any]:
    """Port the V12.3 starter-prior correction that is active under V13.10."""
    league = inputs.league
    old_home_opp = opponent_factor(inputs.away.team_era, inputs.away.starter, league)
    new_home_opp = opponent_factor(inputs.away.team_era, inputs.away.enhanced_starter, league)
    old_away_opp = opponent_factor(inputs.home.team_era, inputs.home.starter, league)
    new_away_opp = opponent_factor(inputs.home.team_era, inputs.home.enhanced_starter, league)

    new_home = _clamp(_num(home_mu) * new_home_opp / max(1e-9, old_home_opp), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    new_away = _clamp(_num(away_mu) * new_away_opp / max(1e-9, old_away_opp), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    return {
        "home_mu": new_home,
        "away_mu": new_away,
        "home_delta": new_home - _num(home_mu),
        "away_delta": new_away - _num(away_mu),
        "home_old_opponent_factor": old_home_opp,
        "home_new_opponent_factor": new_home_opp,
        "away_old_opponent_factor": old_away_opp,
        "away_new_opponent_factor": new_away_opp,
        "starter_model": "current-season + N-1/N-2 prior shrinkage",
        "baseline_schema": "v12.3-structural-v1",
    }


def project(inputs: StructuralInputs) -> dict[str, Any]:
    base = legacy_structural_projection(inputs)
    starter = rescale_for_enhanced_starters(base["home_mu"], base["away_mu"], inputs)
    return {
        "home_mu": starter["home_mu"],
        "away_mu": starter["away_mu"],
        "legacy_base": base,
        "starter_structural_adjustment": starter,
        "baseline_schema": "v12.3-structural-v1",
    }


def historical_pitcher_prior(seasons: list[tuple[dict[str, Any], float]]) -> dict[str, float]:
    """Combine N-1/N-2 pitching seasons exactly as the V12.3 starter prior does.

    Input weights should be 0.65 for N-1 and 0.35 for N-2. Each season is
    additionally weighted by min(1, IP/100). Empty seasons are ignored.
    """
    rows: list[tuple[dict[str, Any], float]] = []
    for stats, base_weight in seasons:
        ip = _num((stats or {}).get("inningsPitched"), 0.0)
        if ip > 0:
            rows.append((stats, float(base_weight) * min(1.0, ip / 100.0)))
    if not rows:
        return {}
    total_weight = sum(weight for _stats, weight in rows)

    def avg(key: str, default: float) -> float:
        return sum(_num(stats.get(key), default) * weight for stats, weight in rows) / total_weight

    return {
        "era": avg("era", 4.35),
        "whip": avg("whip", 1.32),
        "k9": avg("strikeoutsPer9Inn", 8.5),
        "bb9": avg("walksPer9Inn", 3.2),
        "hr9": avg("homeRunsPer9", 1.15),
    }


def enhance_starter(current: dict[str, Any], prior: dict[str, Any], fallback: Starter | None = None) -> Starter:
    """Port the active V12.3 current-season/prior starter shrinkage."""
    fallback = fallback or Starter(era=4.35, whip=1.32, k9=8.5, bb9=3.2, hr9=1.15)
    current = current or {}
    prior = prior or {}
    innings = _num(current.get("inningsPitched"), fallback.innings)
    current_ok = bool(current and current.get("era") is not None and current.get("whip") is not None)
    prior_ok = bool(prior)
    weight = _clamp(innings / (innings + 60.0), 0.0, 1.0) if current_ok else 0.0

    def value(current_key: str, prior_key: str, default: float) -> float:
        cur = _num(current.get(current_key), default)
        old = _num(prior.get(prior_key), default)
        return weight * cur + (1.0 - weight) * old if (current_ok or prior_ok) else default

    return Starter(
        era=value("era", "era", 4.35),
        whip=value("whip", "whip", 1.32),
        k9=value("strikeoutsPer9Inn", "k9", 8.5),
        bb9=value("walksPer9Inn", "bb9", 3.2),
        hr9=value("homeRunsPer9", "hr9", 1.15),
        innings=innings,
        sample_weight=weight,
    )
