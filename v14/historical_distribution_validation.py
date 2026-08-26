from __future__ import annotations

"""Bounded historical validation of V14 score-distribution parameters.

The run-mean challenger is fitted first. Distribution parameters are then
selected on a deterministic 2021-2024 sample, validated on 2025, and audited on
frozen 2026. This module never writes the champion contract.
"""

from typing import Any

from .distribution_tuning import _evaluate, _paired, _public
from .historical_team_challenger import candidate_runs

GRID = tuple((d, s) for d in (5.5, 7.5, 9.0, 12.0) for s in (0.00, 0.08, 0.16))
CHAMPION = (7.5, 0.08)


def _sample(pairs: list[tuple[dict[str, Any], dict[str, Any]]], maximum: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if len(pairs) <= maximum:
        return list(pairs)
    step = len(pairs) / maximum
    return [pairs[min(len(pairs) - 1, int(i * step))] for i in range(maximum)]


def _rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]], params: dict[str, float]) -> list[dict[str, Any]]:
    out = []
    for feature, label in pairs:
        h, a = candidate_runs(feature, params)
        out.append({
            "game_pk": str(feature.get("game_pk") or ""),
            "game_date": feature.get("game_date"),
            "analyzed_at": feature.get("as_of"),
            "home": feature.get("home"),
            "away": feature.get("away"),
            "home_mu": h,
            "away_mu": a,
            "total_line": 8.5,
            "home_score": int(label.get("home_score")),
            "away_score": int(label.get("away_score")),
        })
    return out


def _market_nonreg(paired: dict[str, Any], *, frozen: bool) -> bool:
    for row in (paired.get("markets") or {}).values():
        b = row.get("brier_gain") or {}; l = row.get("logloss_gain") or {}
        if int(b.get("n") or 0) < 250:
            return False
        b_floor = -0.003 if frozen else -0.0015
        l_floor = -0.006 if frozen else -0.003
        if b.get("ci95_lower") is None or float(b["ci95_lower"]) < b_floor:
            return False
        if l.get("ci95_lower") is None or float(l["ci95_lower"]) < l_floor:
            return False
    return True


def build(split: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]], params: dict[str, float]) -> dict[str, Any]:
    tuning_rows = _rows(_sample(split["tuning"], 500), params)
    validation_rows = _rows(_sample(split["validation"], 400), params)
    frozen_rows = _rows(_sample(split["frozen_test"], 400), params)
    scored = []
    for dispersion, sigma in GRID:
        score = _evaluate(tuning_rows, dispersion, sigma)
        if score.get("score_nll") is not None:
            scored.append((float(score["score_nll"]), dispersion, sigma, score))
    if not scored:
        return {"schema": "pulsar-v14-historical-distribution-v1", "status": "COLLECTING", "auto_activation": False}
    _, dispersion, sigma, train_score = min(scored, key=lambda x: x[0])
    validation_candidate = _evaluate(validation_rows, dispersion, sigma)
    validation_champion = _evaluate(validation_rows, *CHAMPION)
    frozen_candidate = _evaluate(frozen_rows, dispersion, sigma)
    frozen_champion = _evaluate(frozen_rows, *CHAMPION)
    vp = _paired(validation_candidate, validation_champion)
    fp = _paired(frozen_candidate, frozen_champion)
    vg = vp.get("score_nll_gain") or {}; fg = fp.get("score_nll_gain") or {}
    same_as_champion = (float(dispersion), float(sigma)) == CHAMPION
    validation_pass = bool(vg.get("ci95_lower") is not None and float(vg["ci95_lower"]) > 0 and _market_nonreg(vp, frozen=False))
    frozen_nonreg = bool(fg.get("mean") is not None and float(fg["mean"]) >= 0 and fg.get("ci95_lower") is not None and float(fg["ci95_lower"]) >= -0.003 and _market_nonreg(fp, frozen=True))
    passes = bool(not same_as_champion and validation_pass and frozen_nonreg)
    return {
        "schema": "pulsar-v14-historical-distribution-v1",
        "role": "RESEARCH_EVIDENCE_ONLY",
        "status": "HISTORICAL_DISTRIBUTION_CANDIDATE" if passes else "KEEP_CURRENT_DISTRIBUTION",
        "passes": passes,
        "auto_activation": False,
        "sample_policy": {"tuning": len(tuning_rows), "validation_2025": len(validation_rows), "frozen_2026": len(frozen_rows), "outcome_independent_even_temporal_sampling": True},
        "candidate": {"dispersion": dispersion, "environment_sigma": sigma, "tuning": _public(train_score)},
        "champion": {"dispersion": CHAMPION[0], "environment_sigma": CHAMPION[1]},
        "validation_2025": {"candidate": _public(validation_candidate), "champion": _public(validation_champion), "paired": vp, "passes": validation_pass},
        "frozen_2026": {"candidate": _public(frozen_candidate), "champion": _public(frozen_champion), "paired": fp, "nonregression": frozen_nonreg},
        "gate": "candidate selected only on 2021-2024; 2025 score-NLL paired CI95 >0 plus market non-regression; frozen 2026 score-NLL point gain >=0 and no significant market regression",
        "native_live_confirmation_required": True,
    }
