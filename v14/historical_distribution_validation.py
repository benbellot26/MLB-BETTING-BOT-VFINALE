from __future__ import annotations

"""Strict historical validation of V14 score-distribution parameters.

Distribution parameters are selected against the strict PIT team-history
baseline only. This deliberately isolates dispersion/environment variance from
the separately tuned team-run challenger, which may be rejected downstream.
The complete untouched 2025 and frozen 2026 holdouts are used for the final
gate; a bounded deterministic 2021-2024 sample is used only for grid selection.
No result from this module can alter the champion automatically.

The historical team dataset does not contain the exact market total line that
was available for each game. Score-NLL and ML/RL diagnostics are therefore the
primary historical evidence. Total-market non-regression is evaluated at a
fixed synthetic 8.5 solely as a distribution diagnostic and is never described
as line-by-line market validation.
"""

from typing import Any, Callable

from .distribution_tuning import _evaluate, _paired, _public
from .historical_team_challenger import baseline_runs, candidate_runs

GRID = tuple((d, s) for d in (5.5, 7.5, 9.0, 12.0) for s in (0.00, 0.08, 0.16))
CHAMPION = (7.5, 0.08)
DIAGNOSTIC_TOTAL_LINE = 8.5
RunPredictor = Callable[[dict[str, Any]], tuple[float, float]]


def _sample(pairs: list[tuple[dict[str, Any], dict[str, Any]]], maximum: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if len(pairs) <= maximum:
        return list(pairs)
    step = len(pairs) / maximum
    return [pairs[min(len(pairs) - 1, int(i * step))] for i in range(maximum)]


def _rows(pairs: list[tuple[dict[str, Any], dict[str, Any]]], predictor: RunPredictor) -> list[dict[str, Any]]:
    out = []
    for feature, label in pairs:
        h, a = predictor(feature)
        out.append({
            "game_pk": str(feature.get("game_pk") or ""),
            "game_date": feature.get("game_date"),
            "analyzed_at": feature.get("as_of"),
            "home": feature.get("home"),
            "away": feature.get("away"),
            "home_mu": h,
            "away_mu": a,
            "total_line": DIAGNOSTIC_TOTAL_LINE,
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


def _paired_gate(candidate: dict[str, Any], champion: dict[str, Any], *, frozen: bool) -> tuple[dict[str, Any], bool]:
    paired = _paired(candidate, champion)
    gain = paired.get("score_nll_gain") or {}
    if frozen:
        passed = bool(
            gain.get("mean") is not None
            and float(gain["mean"]) >= 0
            and gain.get("ci95_lower") is not None
            and float(gain["ci95_lower"]) >= -0.003
            and _market_nonreg(paired, frozen=True)
        )
    else:
        passed = bool(
            gain.get("ci95_lower") is not None
            and float(gain["ci95_lower"]) > 0
            and _market_nonreg(paired, frozen=False)
        )
    return paired, passed


def build(split: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]], run_params: dict[str, float] | None = None) -> dict[str, Any]:
    tuning_rows = _rows(_sample(split["tuning"], 500), baseline_runs)
    validation_rows = _rows(list(split["validation"]), baseline_runs)
    frozen_rows = _rows(list(split["frozen_test"]), baseline_runs)
    scored = []
    for dispersion, sigma in GRID:
        score = _evaluate(tuning_rows, dispersion, sigma)
        if score.get("score_nll") is not None:
            scored.append((float(score["score_nll"]), dispersion, sigma, score))
    if not scored:
        return {"schema": "pulsar-v14-historical-distribution-v2", "status": "COLLECTING", "auto_activation": False}
    _, dispersion, sigma, train_score = min(scored, key=lambda x: x[0])
    validation_candidate = _evaluate(validation_rows, dispersion, sigma)
    validation_champion = _evaluate(validation_rows, *CHAMPION)
    frozen_candidate = _evaluate(frozen_rows, dispersion, sigma)
    frozen_champion = _evaluate(frozen_rows, *CHAMPION)
    vp, validation_pass = _paired_gate(validation_candidate, validation_champion, frozen=False)
    fp, frozen_nonreg = _paired_gate(frozen_candidate, frozen_champion, frozen=True)

    sensitivity = {"status": "NOT_RUN"}
    if run_params:
        predictor = lambda row: candidate_runs(row, run_params)
        sv_rows = _rows(list(split["validation"]), predictor)
        sf_rows = _rows(list(split["frozen_test"]), predictor)
        sv_candidate = _evaluate(sv_rows, dispersion, sigma); sv_champion = _evaluate(sv_rows, *CHAMPION)
        sf_candidate = _evaluate(sf_rows, dispersion, sigma); sf_champion = _evaluate(sf_rows, *CHAMPION)
        svp, sv_pass = _paired_gate(sv_candidate, sv_champion, frozen=False)
        sfp, sf_pass = _paired_gate(sf_candidate, sf_champion, frozen=True)
        sensitivity = {
            "status": "SENSITIVITY_ONLY",
            "run_mean_source": "REJECTED_TEAM_RUN_CHALLENGER",
            "can_authorize_promotion": False,
            "validation_2025": {"paired": svp, "passes": sv_pass},
            "frozen_2026": {"paired": sfp, "nonregression": sf_pass},
        }

    same_as_champion = (float(dispersion), float(sigma)) == CHAMPION
    passes = bool(not same_as_champion and validation_pass and frozen_nonreg)
    return {
        "schema": "pulsar-v14-historical-distribution-v2",
        "role": "RESEARCH_EVIDENCE_ONLY",
        "status": "HISTORICAL_DISTRIBUTION_CANDIDATE" if passes else "KEEP_CURRENT_DISTRIBUTION",
        "passes": passes,
        "auto_activation": False,
        "run_mean_contract": {
            "selection_and_primary_validation": "STRICT_TEAM_HISTORY_BASELINE",
            "current_v14_champion_reconstruction_claimed": False,
            "reason": "distribution effect isolated from the separately rejected team-run challenger",
        },
        "market_line_contract": {
            "total_line": DIAGNOSTIC_TOTAL_LINE,
            "total_line_source": "SYNTHETIC_FIXED_DIAGNOSTIC",
            "historical_actual_total_lines_available": False,
            "total_market_claim": "NON_REGRESSION_AT_FIXED_8_5_ONLY",
            "primary_distribution_evidence": "JOINT_SCORE_NLL_PLUS_ML_RL",
            "native_live_line_by_line_confirmation_required": True,
        },
        "sample_policy": {
            "tuning": len(tuning_rows),
            "validation_2025": len(validation_rows),
            "frozen_2026": len(frozen_rows),
            "tuning_outcome_independent_even_temporal_sampling": True,
            "validation_2025_full_holdout": True,
            "frozen_2026_full_holdout": True,
        },
        "candidate": {"dispersion": dispersion, "environment_sigma": sigma, "tuning": _public(train_score)},
        "champion": {"dispersion": CHAMPION[0], "environment_sigma": CHAMPION[1]},
        "validation_2025": {"candidate": _public(validation_candidate), "champion": _public(validation_champion), "paired": vp, "passes": validation_pass},
        "frozen_2026": {"candidate": _public(frozen_candidate), "champion": _public(frozen_champion), "paired": fp, "nonregression": frozen_nonreg},
        "rejected_run_mean_sensitivity": sensitivity,
        "gate": "distribution selected only on 2021-2024 baseline means; full 2025 paired score-NLL CI95 >0 plus ML/RL/fixed-8.5 diagnostic non-regression; full frozen 2026 score-NLL point gain >=0 with CI95 >= -0.003 plus same diagnostics",
        "native_live_confirmation_required": True,
    }
