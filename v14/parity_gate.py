from __future__ import annotations

"""Deterministic parity assessment for the native V14 acquisition cutover.

This module evaluates evidence only. It deliberately has no Discord, workflow,
or publication side effects and cannot authorize a production payload.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ParityThresholds:
    min_comparable_games: int = 8
    min_candidate_coverage: float = 0.90
    max_mean_abs_structural_run_delta: float = 0.03
    max_single_game_abs_structural_run_delta: float = 0.10

    def validated(self) -> "ParityThresholds":
        if self.min_comparable_games < 1:
            raise ValueError("min_comparable_games must be positive")
        if not 0.0 < self.min_candidate_coverage <= 1.0:
            raise ValueError("min_candidate_coverage must be in (0, 1]")
        if self.max_mean_abs_structural_run_delta < 0.0:
            raise ValueError("mean delta threshold must be non-negative")
        if self.max_single_game_abs_structural_run_delta < 0.0:
            raise ValueError("max delta threshold must be non-negative")
        return self


DEFAULT_THRESHOLDS = ParityThresholds()


def _coverage(candidate: dict[str, Any]) -> float:
    coverage = candidate.get("coverage") or {}
    scheduled = int(coverage.get("scheduled_future_games") or 0)
    priced = int(coverage.get("priced_games") or 0)
    if scheduled <= 0:
        return 0.0
    return priced / scheduled


def assess_parity(
    candidate: dict[str, Any],
    parity_report: dict[str, Any],
    *,
    thresholds: ParityThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    limits = thresholds.validated()
    comparable = int(parity_report.get("comparable_games") or 0)
    mean_delta = parity_report.get("mean_abs_structural_run_delta")
    max_delta = parity_report.get("max_abs_structural_run_delta")
    coverage = _coverage(candidate)

    checks = {
        "enough_comparable_games": comparable >= limits.min_comparable_games,
        "candidate_coverage": coverage >= limits.min_candidate_coverage,
        "mean_structural_delta": (
            mean_delta is not None
            and float(mean_delta) <= limits.max_mean_abs_structural_run_delta
        ),
        "max_structural_delta": (
            max_delta is not None
            and float(max_delta) <= limits.max_single_game_abs_structural_run_delta
        ),
    }
    passed = all(checks.values())
    return {
        "schema": "pulsar-v14-native-parity-assessment-v1",
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "thresholds": asdict(limits),
        "observed": {
            "comparable_games": comparable,
            "candidate_coverage": coverage,
            "mean_abs_structural_run_delta": mean_delta,
            "max_abs_structural_run_delta": max_delta,
        },
        "checks": checks,
        # Assessment is evidence only. Publication authorization remains separate.
        "publication_authorized": False,
        "cutover_authorized": False,
    }
