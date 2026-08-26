from __future__ import annotations

"""Statistical betting certification, separate from software PRODUCTION.

Certification is market-specific.  A weak Total model can no longer block a
strong ML model, and a strong ML model cannot authorize Total bets.  New V14.4
performance reports require paired model-vs-sharp confidence intervals.  Older
synthetic/test artifacts remain readable for backwards compatibility but are
labelled as legacy inference.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

PERFORMANCE=Path("data/v14_performance.json")
CALIBRATION=Path("data/v14_calibration.json")
PAPER_PERFORMANCE=Path("data/v14_paper_bet_performance.json")
MIN_GAMES=600
MIN_MARKET_N=400
MAX_ECE=0.05
MIN_PAIRED_SHARP_N=400
MIN_PAPER_CLV_N=100
MIN_POSITIVE_CLV_RATE=0.52
MAX_ROLLING_ECE=0.07
MIN_ROLLING_N=100
MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")


def _load(path: Path | str) -> dict[str,Any]:
    target=Path(path)
    if not target.exists(): return {}
    try: row=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {}
    return row if isinstance(row,dict) else {}


def _calibration_accepted(calibrator: dict[str,Any]) -> bool:
    # v1 compatibility: an active transform had already passed strict OOS.
    return calibrator.get("accepted") is True or calibrator.get("active") is True


def _paper_for_market(paper: dict[str,Any], market: str) -> dict[str,Any]:
    by_market=paper.get("by_market") or {}
    scoped=by_market.get(market) or {}
    return (scoped.get("clv") or scoped) if scoped else (paper.get("clv") or {})


def _drift_failures(performance: dict[str,Any], market: str) -> list[str]:
    rolling=(((performance.get("segments") or {}).get("rolling") or {}).get("60d") or {})
    metrics=(rolling.get("markets") or {}).get(market) or {}
    if int(metrics.get("n") or 0)<MIN_ROLLING_N: return []
    failures=[]; ece=metrics.get("ece")
    if ece is not None and float(ece)>MAX_ROLLING_ECE: failures.append("rolling_60d_calibration_drift")
    sharp=metrics.get("sharp_benchmark") or {}; paired=int(sharp.get("paired_n") or sharp.get("n") or 0)
    lower=sharp.get("brier_gain_ci95_lower")
    if paired>=MIN_ROLLING_N and lower is not None and float(lower)<-0.002: failures.append("rolling_60d_sharp_regression")
    return failures


def _sharp_failures(sharp: dict[str,Any], *, strict_ci: bool) -> list[str]:
    failures=[]; paired=int(sharp.get("paired_n") or sharp.get("n") or 0)
    if paired<MIN_PAIRED_SHARP_N: return [f"sharp_paired_n<{MIN_PAIRED_SHARP_N}"]
    if strict_ci:
        b_lower=sharp.get("brier_gain_ci95_lower"); l_lower=sharp.get("logloss_gain_ci95_lower")
        if b_lower is None or float(b_lower)<=0: failures.append("paired_brier_gain_ci95_not_positive")
        # LogLoss is a secondary non-regression gate; allow a tiny statistical
        # tolerance but never a clearly negative lower bound.
        if l_lower is None or float(l_lower)<-0.001: failures.append("paired_logloss_ci95_regression")
    else:
        if sharp.get("brier_gain_vs_sharp") is None or float(sharp.get("brier_gain_vs_sharp"))<0: failures.append("model_not_beating_sharp_brier")
        if sharp.get("logloss_gain_vs_sharp") is None or float(sharp.get("logloss_gain_vs_sharp"))<0: failures.append("model_not_beating_sharp_logloss")
    return failures


def evaluate(performance: dict[str,Any]|None=None, calibration: dict[str,Any]|None=None, paper_performance: dict[str,Any]|None=None) -> dict[str,Any]:
    perf=performance or {}; cal=calibration or {}; paper=_load(PAPER_PERFORMANCE) if paper_performance is None else paper_performance
    generation_ok=perf.get("model_generation") in {None,MODEL_GENERATION}; games=int(perf.get("games_settled") or 0)
    strict_ci=str(perf.get("schema") or "").startswith("pulsar-v14-performance-v5")
    global_probability_reasons=[]
    if not generation_ok: global_probability_reasons.append("generation_mismatch")
    if games<MIN_GAMES: global_probability_reasons.append(f"games_settled<{MIN_GAMES}")

    perf_markets=perf.get("markets") or {}; calibrators=cal.get("calibrators") or {}; market_status={}
    any_probability=False; any_betting=False
    for market in MARKETS:
        metrics=perf_markets.get(market) or {}; failures=list(global_probability_reasons); n=int(metrics.get("n") or 0); ece=metrics.get("ece")
        if n<MIN_MARKET_N: failures.append(f"n<{MIN_MARKET_N}")
        if ece is None or float(ece)>MAX_ECE: failures.append(f"ece>{MAX_ECE:.2f}_or_missing")
        calibrator=calibrators.get(f"MARKET:{market}") or {}
        if not _calibration_accepted(calibrator): failures.append("calibration_not_oos_accepted")
        failures.extend(_sharp_failures(metrics.get("sharp_benchmark") or {},strict_ci=strict_ci))
        failures.extend(_drift_failures(perf,market))
        probability_certified=not failures; any_probability=any_probability or probability_certified

        clv=_paper_for_market(paper,market); betting_failures=list(failures); clv_n=int(clv.get("n") or 0); mean=clv.get("mean_clv"); positive=clv.get("positive_rate")
        if clv_n<MIN_PAPER_CLV_N: betting_failures.append(f"paper_clv_n<{MIN_PAPER_CLV_N}")
        if mean is None or float(mean)<=0: betting_failures.append("paper_mean_clv_not_positive")
        if positive is None or float(positive)<MIN_POSITIVE_CLV_RATE: betting_failures.append(f"paper_positive_clv_rate<{MIN_POSITIVE_CLV_RATE:.2f}")
        ci=clv.get("mean_clv_ci95_lower")
        if ci is not None and float(ci)<=0: betting_failures.append("paper_clv_ci95_not_positive")
        betting_certified=probability_certified and not betting_failures; any_betting=any_betting or betting_certified
        market_status[market]={"probability_certified":probability_certified,"betting_certified":betting_certified,"probability_status":"PROBABILITY_CERTIFIED" if probability_certified else "PROBABILITY_RESEARCH","betting_status":"BETTING_CERTIFIED" if betting_certified else "RESEARCH_ONLY","n":n,"ece":ece,"calibration_status":calibrator.get("status"),"failures":failures,"betting_failures":betting_failures,"paper_clv":{"n":clv_n,"mean_clv":mean,"positive_rate":positive,"mean_clv_ci95_lower":ci}}

    # Compatibility: previous callers interpreted `probability_certified` and
    # `certified` globally.  They now mean at least one market is authorized;
    # the decision layer must additionally check its own market flag.
    probability_reasons=sorted({reason for row in market_status.values() for reason in row["failures"]}) if not any_probability else []
    betting_reasons=sorted({reason for row in market_status.values() for reason in row["betting_failures"]}) if not any_betting else []
    return {"schema":"pulsar-v14-betting-certification-v3","model_generation":MODEL_GENERATION,"software_role":"PRODUCTION","generated_at":datetime.now(timezone.utc).isoformat(),
            "probability_status":"PROBABILITY_CERTIFIED" if any_probability else "PROBABILITY_RESEARCH","probability_certified":any_probability,
            "betting_status":"BETTING_CERTIFIED" if any_betting else "RESEARCH_ONLY","certified":any_betting,"markets":market_status,
            "probability_reasons":probability_reasons,"reasons":betting_reasons,"paired_inference_required":strict_ci,
            "paper_clv":paper.get("clv") or {},
            "policy":{"min_games":MIN_GAMES,"min_market_n":MIN_MARKET_N,"max_ece":MAX_ECE,"min_paired_sharp_n":MIN_PAIRED_SHARP_N,"min_paper_clv_n":MIN_PAPER_CLV_N,"min_positive_clv_rate":MIN_POSITIVE_CLV_RATE,"market_specific_authorization":True,"rolling_drift_window_days":60}}


def load_status(performance_path: Path|str=PERFORMANCE, calibration_path: Path|str=CALIBRATION, paper_path: Path|str=PAPER_PERFORMANCE) -> dict[str,Any]:
    return evaluate(_load(performance_path),_load(calibration_path),_load(paper_path))
