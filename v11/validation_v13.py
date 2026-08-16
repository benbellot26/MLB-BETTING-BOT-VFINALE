from __future__ import annotations

import math
import os
import random
from collections import defaultdict
from typing import Any, Callable

MIN_COMPATIBLE_GAMES = int(os.getenv("V13_MIN_COMPATIBLE_GAMES", "600") or 600)
MIN_OUTER_HOLDOUT_GAMES = int(os.getenv("V13_MIN_OUTER_HOLDOUT_GAMES", "200") or 200)
MIN_WALK_FORWARD_WINDOWS = int(os.getenv("V13_MIN_WF_WINDOWS", "5") or 5)
MIN_MARKET_SAFETY_N = int(os.getenv("V13_MIN_MARKET_SAFETY_N", "100") or 100)
MAX_MARKET_BRIER_REGRESSION = float(os.getenv("V13_MAX_MARKET_BRIER_REGRESSION", "0.002") or .002)
BOOTSTRAPS = int(os.getenv("V13_VALIDATION_BOOTSTRAPS", "1000") or 1000)


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    pos = max(0.0, min(len(xs)-1, q*(len(xs)-1)))
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo]*(hi-pos)+xs[hi]*(pos-lo)


def paired_bootstrap_ci(deltas_by_day: dict[str,list[float]], seed: int = 13013) -> list[float | None]:
    days = sorted(k for k,v in deltas_by_day.items() if v)
    if len(days) < 8:
        return [None,None]
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(BOOTSTRAPS):
        chosen = [days[rng.randrange(len(days))] for _ in days]
        vals = [d for day in chosen for d in deltas_by_day[day]]
        samples.append(sum(vals)/len(vals) if vals else 0.0)
    return [_percentile(samples,.025), _percentile(samples,.975)]


def strict_promotion_gate(
    *,
    compatible_games: int,
    outer_holdout_games: int,
    walk_forward_windows: list[dict[str,Any]],
    paired_brier_deltas_by_day: dict[str,list[float]],
    logloss_gain: float,
    market_metrics: dict[str,dict[str,Any]],
    calibration_metrics: dict[str,Any] | None = None,
) -> dict[str,Any]:
    ci = paired_bootstrap_ci(paired_brier_deltas_by_day)
    lower = ci[0]
    wf_valid = [w for w in walk_forward_windows if int(w.get("test_games") or 0) > 0]
    wf_positive = [w for w in wf_valid if _num(w.get("brier_improvement"), -1) > 0 and _num(w.get("logloss_improvement"), -1) >= 0]
    wf_rate = len(wf_positive)/len(wf_valid) if wf_valid else 0.0
    market_safe = True
    market_detail = {}
    for market,m in market_metrics.items():
        n = int(m.get("n") or 0)
        regression = _num(m.get("candidate_brier"),9)-_num(m.get("baseline_brier"),9)
        safe = n < MIN_MARKET_SAFETY_N or regression <= MAX_MARKET_BRIER_REGRESSION
        market_detail[market] = {"n":n,"brier_regression":regression,"safe":safe}
        market_safe = market_safe and safe
    cal = calibration_metrics or {}
    ece = cal.get("ece")
    slope = cal.get("slope")
    intercept = cal.get("intercept")
    calibration_safe = True
    if ece is not None:
        calibration_safe &= _num(ece,9) <= .03
    if slope is not None:
        calibration_safe &= .75 <= _num(slope) <= 1.25
    if intercept is not None:
        calibration_safe &= abs(_num(intercept)) <= .20
    checks = {
        "compatible_volume": compatible_games >= MIN_COMPATIBLE_GAMES,
        "outer_holdout_volume": outer_holdout_games >= MIN_OUTER_HOLDOUT_GAMES,
        "walk_forward_windows": len(wf_valid) >= MIN_WALK_FORWARD_WINDOWS,
        "walk_forward_consistency": wf_rate >= .80,
        "paired_brier_ci_positive": lower is not None and lower > 0,
        "logloss_nonnegative": _num(logloss_gain,-999) >= 0,
        "market_safe": market_safe,
        "calibration_safe": calibration_safe,
    }
    return {
        "passes": all(checks.values()),
        "checks": checks,
        "paired_brier_improvement_ci95": ci,
        "walk_forward_valid_windows": len(wf_valid),
        "walk_forward_positive_rate": wf_rate,
        "market_detail": market_detail,
        "calibration_safe": calibration_safe,
        "policy": "strict-v13; frozen test reporting-only; day-block bootstrap",
    }
