from __future__ import annotations

"""Conservative probability uncertainty bands for Pulsar V14.

These bands are decision-safety intervals, not claims of exact Bayesian credible
intervals. Before calibration evidence matures they intentionally remain wide.
"""

import math
from typing import Any

BASE_HALF_WIDTH = {"ML": 0.060, "RL_HOME_-1.5": 0.075, "RL_AWAY_-1.5": 0.075, "TOTAL_OVER": 0.085}
PAIR_MAP = {"ML": ("home_ml", "away_ml"), "RL_HOME_-1.5": ("home_minus_1_5", "away_plus_1_5"), "RL_AWAY_-1.5": ("away_minus_1_5", "home_plus_1_5"), "TOTAL_OVER": ("over", "under")}


def _num(value: Any) -> float | None:
    try: out = float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _quality_penalty(data_quality: dict[str, Any] | None, *, starter_degraded: bool, market_fresh: bool | None) -> float:
    q = data_quality or {}; penalty = 0.0
    if starter_degraded: penalty += 0.035
    if q.get("eligible") is False: penalty += 0.040
    home_count = int(_num(q.get("home_lineup_count")) or 0); away_count = int(_num(q.get("away_lineup_count")) or 0)
    if min(home_count, away_count) < 9: penalty += 0.012
    if min(home_count, away_count) < 5: penalty += 0.010
    if market_fresh is False: penalty += 0.015
    return min(0.08, penalty)


def intervals(probabilities: dict[str, Any], calibration: dict[str, Any] | None, *, data_quality: dict[str, Any] | None = None, starter_degraded: bool = False, market_fresh: bool | None = None) -> dict[str, Any]:
    cal_markets = (calibration or {}).get("markets") or {}; penalty = _quality_penalty(data_quality, starter_degraded=starter_degraded, market_fresh=market_fresh); selections: dict[str, Any] = {}
    for market, (left, right) in PAIR_MAP.items():
        p = _num(probabilities.get(left))
        if p is None: continue
        meta = cal_markets.get(market) or {}; n = int(meta.get("n") or 0); active = meta.get("active") is True
        if active and n > 0:
            holdout = meta.get("holdout") or {}; ece = abs(_num(holdout.get("ece")) or 0.0); sampling = 1.64 * math.sqrt(max(1e-8, p * (1 - p)) / max(25, n)); half = max(0.025, sampling + 0.50 * ece)
        else: half = BASE_HALF_WIDTH[market]
        half = min(0.15, half + penalty); lo, hi = max(0.0, p - half), min(1.0, p + half)
        selections[left] = {"probability": p, "lower": lo, "upper": hi, "half_width_pp": 100 * half, "calibration_active": active, "evidence_n": n}
        rp = 1 - p; selections[right] = {"probability": rp, "lower": 1 - hi, "upper": 1 - lo, "half_width_pp": 100 * half, "calibration_active": active, "evidence_n": n}
    return {"schema": "pulsar-v14-probability-uncertainty-v1", "method": "conservative-calibration-aware-decision-band", "starter_degraded": bool(starter_degraded), "market_freshness_verified": market_fresh, "quality_penalty_pp": 100 * penalty, "selections": selections}
