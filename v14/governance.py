from __future__ import annotations

"""Champion/challenger governance for Pulsar V14.

This module is intentionally unable to promote or mutate production. It only
assesses whether a challenger evaluation satisfies an explicit promotion
contract. Promotion remains a separate manual code/review action.
"""

from dataclasses import dataclass
from typing import Any

MIN_HOLDOUT_GAMES = 100
MAX_MARKET_BRIER_REGRESSION = 0.0025
MIN_BRIER_IMPROVEMENT = 0.0020
MIN_LOGLOSS_IMPROVEMENT = 0.0040
MAX_ABS_CALIBRATION_BIAS_PP = 3.0


@dataclass(frozen=True)
class PromotionDecision:
    eligible: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "automatic_promotion": False,
            "requires_manual_review": True,
        }


def assess_challenger(champion: dict[str, Any], challenger: dict[str, Any]) -> PromotionDecision:
    """Assess a chronological holdout comparison; never performs promotion."""
    reasons: list[str] = []
    n = int(challenger.get("holdout_games") or 0)
    if n < MIN_HOLDOUT_GAMES:
        reasons.append(f"holdout_games<{MIN_HOLDOUT_GAMES}")

    cb = champion.get("overall") or {}
    xb = challenger.get("overall") or {}
    c_brier = cb.get("brier"); x_brier = xb.get("brier")
    c_log = cb.get("log_loss"); x_log = xb.get("log_loss")
    if c_brier is None or x_brier is None or (float(c_brier) - float(x_brier)) < MIN_BRIER_IMPROVEMENT:
        reasons.append("insufficient_brier_improvement")
    if c_log is None or x_log is None or (float(c_log) - float(x_log)) < MIN_LOGLOSS_IMPROVEMENT:
        reasons.append("insufficient_logloss_improvement")

    bias = xb.get("max_abs_calibration_bias_pp")
    if bias is None or float(bias) > MAX_ABS_CALIBRATION_BIAS_PP:
        reasons.append("calibration_gate_failed")

    champion_markets = champion.get("markets") or {}
    challenger_markets = challenger.get("markets") or {}
    for market, cm in champion_markets.items():
        xm = challenger_markets.get(market)
        if not xm or cm.get("brier") is None or xm.get("brier") is None:
            reasons.append(f"missing_market:{market}")
            continue
        if float(xm["brier"]) - float(cm["brier"]) > MAX_MARKET_BRIER_REGRESSION:
            reasons.append(f"market_regression:{market}")

    if challenger.get("validation") != "chronological_holdout":
        reasons.append("invalid_validation_protocol")
    if challenger.get("data_leakage_detected") is not False:
        reasons.append("leakage_gate_failed")

    return PromotionDecision(eligible=not reasons, reasons=tuple(reasons))


def promotion_contract() -> dict[str, Any]:
    return {
        "schema": "pulsar-v14-promotion-contract-v1",
        "automatic_promotion": False,
        "production_mutation_allowed": False,
        "minimum_holdout_games": MIN_HOLDOUT_GAMES,
        "minimum_brier_improvement": MIN_BRIER_IMPROVEMENT,
        "minimum_logloss_improvement": MIN_LOGLOSS_IMPROVEMENT,
        "maximum_absolute_calibration_bias_pp": MAX_ABS_CALIBRATION_BIAS_PP,
        "maximum_market_brier_regression": MAX_MARKET_BRIER_REGRESSION,
        "required_validation": "chronological_holdout",
        "required_leakage_status": False,
        "promotion_action": "explicit reviewed code change only",
    }
