from __future__ import annotations

"""Statistical betting certification, deliberately separate from software PRODUCTION."""

import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

PERFORMANCE = Path("data/v14_performance.json")
CALIBRATION = Path("data/v14_calibration.json")
MIN_GAMES = 600
MIN_MARKET_N = 400
MAX_ECE = 0.05
MIN_CLV_N = 100


def _load(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists(): return {}
    try:
        row = json.loads(target.read_text(encoding="utf-8")); return row if isinstance(row, dict) else {}
    except Exception: return {}


def evaluate(performance: dict[str, Any] | None = None, calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    perf = performance or {}; cal = calibration or {}; reasons: list[str] = []; games = int(perf.get("games_settled") or 0)
    if perf.get("model_generation") not in {None, MODEL_GENERATION}: reasons.append("generation_mismatch")
    if games < MIN_GAMES: reasons.append(f"games_settled<{MIN_GAMES}")
    markets = perf.get("markets") or {}; calibs = cal.get("calibrators") or {}; market_status: dict[str, Any] = {}
    for market in ("ML", "RL_HOME_-1.5", "RL_AWAY_-1.5", "TOTAL_OVER"):
        m = markets.get(market) or {}; n = int(m.get("n") or 0); ece = m.get("ece"); calrow = calibs.get(f"MARKET:{market}") or {}; failures: list[str] = []
        if n < MIN_MARKET_N: failures.append(f"n<{MIN_MARKET_N}")
        if ece is None or float(ece) > MAX_ECE: failures.append(f"ece>{MAX_ECE:.2f}_or_missing")
        if calrow.get("active") is not True: failures.append("calibration_not_oos_active")
        sharp = m.get("sharp_benchmark") or {}
        if int(sharp.get("n") or 0) < MIN_MARKET_N: failures.append("sharp_benchmark_insufficient")
        elif sharp.get("brier_gain_vs_sharp") is None or float(sharp.get("brier_gain_vs_sharp")) < 0 or sharp.get("logloss_gain_vs_sharp") is None or float(sharp.get("logloss_gain_vs_sharp")) < 0: failures.append("model_not_beating_sharp")
        market_status[market] = {"certified": not failures, "n": n, "failures": failures}; reasons.extend(f"{market}:{x}" for x in failures)
    clv = perf.get("clv") or {}
    if clv.get("status") != "AVAILABLE" or int(clv.get("n") or 0) < MIN_CLV_N or clv.get("mean_clv") is None or float(clv.get("mean_clv") or 0) <= 0: reasons.append("positive_official_clv_not_demonstrated")
    certified = not reasons and all(v.get("certified") for v in market_status.values())
    return {"schema": "pulsar-v14-betting-certification-v1", "model_generation": MODEL_GENERATION, "software_role": "PRODUCTION", "betting_status": "BETTING_CERTIFIED" if certified else "RESEARCH_ONLY", "certified": certified, "games_settled": games, "markets": market_status, "reasons": reasons, "policy": {"min_games": MIN_GAMES, "min_market_n": MIN_MARKET_N, "max_ece": MAX_ECE, "min_clv_n": MIN_CLV_N}}


def load_status(performance_path: Path | str = PERFORMANCE, calibration_path: Path | str = CALIBRATION) -> dict[str, Any]:
    return evaluate(_load(performance_path), _load(calibration_path))
