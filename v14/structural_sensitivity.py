from __future__ import annotations

"""Research-only sensitivity analysis for the frozen structural champion.

This module deliberately re-expresses the small set of hand-authored structural
weights in a shadow implementation. It NEVER participates in production
probability generation. Default weights are parity-tested against
``v14.structural.project``; perturbations are diagnostics only.
"""

from dataclasses import asdict, dataclass
from typing import Any

from .structural import (
    MAX_STRUCTURAL_MU,
    MIN_STRUCTURAL_MU,
    StructuralInputs,
    Starter,
    _clamp,
    _num,
    operational_adjustments,
    ratio,
)


@dataclass(frozen=True)
class StructuralWeights:
    offense_rpg: float = 0.42
    offense_ops: float = 0.33
    offense_lineup_ops: float = 0.25
    starter_era: float = 0.68
    starter_whip: float = 0.32
    opponent_team_era: float = 0.52
    opponent_starter: float = 0.48
    home_multiplier: float = 1.025
    away_multiplier: float = 0.975


DEFAULT_WEIGHTS = StructuralWeights()
WEIGHT_GROUPS = {
    "offense": ("offense_rpg", "offense_ops", "offense_lineup_ops"),
    "starter": ("starter_era", "starter_whip"),
    "opponent": ("opponent_team_era", "opponent_starter"),
}
PERTURBABLE = tuple(asdict(DEFAULT_WEIGHTS))


def _renormalize(weights: StructuralWeights, field: str, multiplier: float) -> StructuralWeights:
    values = asdict(weights)
    group = next((members for members in WEIGHT_GROUPS.values() if field in members), None)
    values[field] = max(1e-9, float(values[field]) * float(multiplier))
    if group:
        total = sum(float(values[name]) for name in group)
        for name in group:
            values[name] = float(values[name]) / total
    return StructuralWeights(**values)


def _starter_quality(starter: Starter, inputs: StructuralInputs, weights: StructuralWeights) -> float:
    league = inputs.league
    return (
        weights.starter_era * ratio(starter.era, league.era)
        + weights.starter_whip * ratio(starter.whip, league.whip)
    )


def _offense_factor(team: Any, inputs: StructuralInputs, weights: StructuralWeights) -> float:
    league = inputs.league
    return (
        weights.offense_rpg * ratio(team.runs_per_game, league.rpg)
        + weights.offense_ops * ratio(team.ops, league.ops)
        + weights.offense_lineup_ops * ratio(team.lineup_ops, league.ops)
    )


def _opponent_factor(team_era: float, starter: Starter, inputs: StructuralInputs, weights: StructuralWeights) -> float:
    league = inputs.league
    return (
        weights.opponent_team_era * ratio(team_era, league.era)
        + weights.opponent_starter * _starter_quality(starter, inputs, weights)
    )


def shadow_project(inputs: StructuralInputs, weights: StructuralWeights = DEFAULT_WEIGHTS) -> dict[str, float]:
    """Reproduce the structural champion with configurable research-only weights."""
    league = inputs.league
    home_offense = _offense_factor(inputs.home, inputs, weights)
    away_offense = _offense_factor(inputs.away, inputs, weights)
    home_opp = _opponent_factor(inputs.away.team_era, inputs.away.starter, inputs, weights)
    away_opp = _opponent_factor(inputs.home.team_era, inputs.home.starter, inputs, weights)
    park = _num(inputs.static_park_factor, 1.0)

    home_mu = league.rpg * home_offense * home_opp * park * weights.home_multiplier
    away_mu = league.rpg * away_offense * away_opp * park * weights.away_multiplier
    home_adj, away_adj = operational_adjustments(inputs)
    home_mu = _clamp(home_mu * (1.0 + home_adj), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    away_mu = _clamp(away_mu * (1.0 + away_adj), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)

    old_home_opp = home_opp
    old_away_opp = away_opp
    new_home_opp = _opponent_factor(inputs.away.team_era, inputs.away.enhanced_starter, inputs, weights)
    new_away_opp = _opponent_factor(inputs.home.team_era, inputs.home.enhanced_starter, inputs, weights)
    home_mu = _clamp(home_mu * new_home_opp / max(1e-9, old_home_opp), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    away_mu = _clamp(away_mu * new_away_opp / max(1e-9, old_away_opp), MIN_STRUCTURAL_MU, MAX_STRUCTURAL_MU)
    return {"home_mu": home_mu, "away_mu": away_mu}


def sensitivity_report(
    inputs: StructuralInputs,
    *,
    perturbations: tuple[float, ...] = (0.10, 0.20),
) -> dict[str, Any]:
    """One-at-a-time coefficient perturbations around the frozen default weights."""
    baseline = shadow_project(inputs, DEFAULT_WEIGHTS)
    rows: list[dict[str, Any]] = []
    for field in PERTURBABLE:
        for magnitude in perturbations:
            for direction in (-1, 1):
                multiplier = 1.0 + direction * float(magnitude)
                varied = _renormalize(DEFAULT_WEIGHTS, field, multiplier)
                result = shadow_project(inputs, varied)
                home_delta = result["home_mu"] - baseline["home_mu"]
                away_delta = result["away_mu"] - baseline["away_mu"]
                rows.append(
                    {
                        "coefficient": field,
                        "perturbation_pct": direction * float(magnitude) * 100.0,
                        "weights": asdict(varied),
                        "home_mu": result["home_mu"],
                        "away_mu": result["away_mu"],
                        "home_delta_runs": home_delta,
                        "away_delta_runs": away_delta,
                        "max_abs_delta_runs": max(abs(home_delta), abs(away_delta)),
                    }
                )
    rows.sort(key=lambda row: float(row["max_abs_delta_runs"]), reverse=True)
    return {
        "schema": "pulsar-v14-structural-sensitivity-v1",
        "role": "RESEARCH_ONLY",
        "champion_impact": False,
        "method": "one-at-a-time coefficient perturbation; mixture groups re-normalized",
        "baseline_weights": asdict(DEFAULT_WEIGHTS),
        "baseline": baseline,
        "scenarios": rows,
        "worst_case": rows[0] if rows else None,
    }


def aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize many game-level sensitivity reports without hiding tails."""
    by_key: dict[tuple[str, float], list[float]] = {}
    for report in reports:
        for row in report.get("scenarios") or []:
            key = (str(row.get("coefficient")), float(row.get("perturbation_pct") or 0.0))
            by_key.setdefault(key, []).append(float(row.get("max_abs_delta_runs") or 0.0))
    summary = []
    for (coefficient, perturbation), values in by_key.items():
        ordered = sorted(values)
        n = len(ordered)
        summary.append(
            {
                "coefficient": coefficient,
                "perturbation_pct": perturbation,
                "n": n,
                "mean_max_abs_delta_runs": sum(ordered) / n if n else None,
                "p95_max_abs_delta_runs": ordered[min(n - 1, int(0.95 * (n - 1)))] if n else None,
                "max_abs_delta_runs": max(ordered) if n else None,
            }
        )
    summary.sort(key=lambda row: float(row.get("p95_max_abs_delta_runs") or 0.0), reverse=True)
    return {
        "schema": "pulsar-v14-structural-sensitivity-summary-v1",
        "role": "RESEARCH_ONLY",
        "champion_impact": False,
        "games": len(reports),
        "summary": summary,
    }
