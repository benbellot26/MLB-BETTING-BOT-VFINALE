from __future__ import annotations

"""Statistical betting certification, deliberately separate from software PRODUCTION.

Certification is two-stage to avoid a circular dependency:
1) probability certification requires volume, calibration and sharp-benchmark
   proper-score evidence;
2) betting certification additionally requires prospective PAPER CLV evidence
   collected from candidates that passed every safety gate except certification.
Official stakes are impossible before stage 2.
"""

import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

PERFORMANCE = Path("data/v14_performance.json")
CALIBRATION = Path("data/v14_calibration.json")
PAPER_PERFORMANCE = Path("data/v14_paper_bet_performance.json")
MIN_GAMES = 600
MIN_MARKET_N = 400
MAX_ECE = 0.05
MIN_PAPER_CLV_N = 100
MIN_POSITIVE_CLV_RATE = 0.52


def _load(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists(): return {}
    try:
        row = json.loads(target.read_text(encoding="utf-8")); return row if isinstance(row, dict) else {}
    except Exception: return {}


def evaluate(performance: dict[str, Any] | None = None, calibration: dict[str, Any] | None = None, paper_performance: dict[str, Any] | None = None) -> dict[str, Any]:
    perf = performance or {}; cal = calibration or {}; paper=paper_performance or {}; probability_reasons: list[str] = []; games = int(perf.get("games_settled") or 0)
    if perf.get("model_generation") not in {None, MODEL_GENERATION}: probability_reasons.append("generation_mismatch")
    if games < MIN_GAMES: probability_reasons.append(f"games_settled<{MIN_GAMES}")
    markets = perf.get("markets") or {}; calibs = cal.get("calibrators") or {}; market_status: dict[str, Any] = {}
    for market in ("ML", "RL_HOME_-1.5", "RL_AWAY_-1.5", "TOTAL_OVER"):
        m = markets.get(market) or {}; n = int(m.get("n") or 0); ece = m.get("ece"); calrow = calibs.get(f"MARKET:{market}") or {}; failures: list[str] = []
        if n < MIN_MARKET_N: failures.append(f"n<{MIN_MARKET_N}")
        if ece is None or float(ece) > MAX_ECE: failures.append(f"ece>{MAX_ECE:.2f}_or_missing")
        if calrow.get("active") is not True: failures.append("calibration_not_oos_active")
        sharp = m.get("sharp_benchmark") or {}
        if int(sharp.get("n") or 0) < MIN_MARKET_N: failures.append("sharp_benchmark_insufficient")
        elif sharp.get("brier_gain_vs_sharp") is None or float(sharp.get("brier_gain_vs_sharp")) < 0 or sharp.get("logloss_gain_vs_sharp") is None or float(sharp.get("logloss_gain_vs_sharp")) < 0: failures.append("model_not_beating_sharp")
        market_status[market] = {"probability_certified": not failures, "n": n, "failures": failures}; probability_reasons.extend(f"{market}:{x}" for x in failures)
    probability_certified = not probability_reasons and all(v.get("probability_certified") for v in market_status.values())

    betting_reasons=list(probability_reasons); paper_clv=paper.get("clv") or {}; clv_n=int(paper_clv.get("n") or 0); mean_clv=paper_clv.get("mean_clv"); positive_rate=paper_clv.get("positive_rate")
    if clv_n < MIN_PAPER_CLV_N: betting_reasons.append(f"paper_clv_n<{MIN_PAPER_CLV_N}")
    if mean_clv is None or float(mean_clv) <= 0: betting_reasons.append("paper_mean_clv_not_positive")
    if positive_rate is None or float(positive_rate) < MIN_POSITIVE_CLV_RATE: betting_reasons.append(f"paper_positive_clv_rate<{MIN_POSITIVE_CLV_RATE:.2f}")
    certified = probability_certified and not betting_reasons
    return {
        "schema": "pulsar-v14-betting-certification-v2", "model_generation": MODEL_GENERATION, "software_role": "PRODUCTION",
        "probability_status":"PROBABILITY_CERTIFIED" if probability_certified else "PROBABILITY_RESEARCH",
        "probability_certified":probability_certified,
        "betting_status": "BETTING_CERTIFIED" if certified else "RESEARCH_ONLY", "certified": certified, "games_settled": games,
        "markets": market_status, "probability_reasons": probability_reasons, "reasons": betting_reasons,
        "paper_clv":{"n":clv_n,"mean_clv":mean_clv,"positive_rate":positive_rate},
        "policy": {"min_games": MIN_GAMES, "min_market_n": MIN_MARKET_N, "max_ece": MAX_ECE, "min_paper_clv_n": MIN_PAPER_CLV_N, "min_positive_clv_rate":MIN_POSITIVE_CLV_RATE}
    }


def load_status(performance_path: Path | str = PERFORMANCE, calibration_path: Path | str = CALIBRATION, paper_path:Path|str=PAPER_PERFORMANCE) -> dict[str, Any]:
    return evaluate(_load(performance_path), _load(calibration_path), _load(paper_path))
