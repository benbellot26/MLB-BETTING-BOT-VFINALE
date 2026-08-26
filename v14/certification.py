from __future__ import annotations

"""Strict statistical betting certification, separate from software PRODUCTION.

Only current-generation, fresh, strict-schema evidence can authorize betting.
Legacy or stale reports remain diagnostic only. Certification is market-specific
and requires accepted calibration, paired superiority to sharp, drift control
and immutable prospective paper CLV with a positive confidence bound.
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
MAX_ECE=.05
MIN_PAIRED_SHARP_N=400
MIN_PAPER_CLV_N=100
MIN_POSITIVE_CLV_RATE=.52
MAX_ROLLING_ECE=.07
MIN_ROLLING_N=100
MAX_EVIDENCE_AGE_HOURS=48.0
MAX_FUTURE_SKEW_MINUTES=10.0
MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")
STRICT_PERFORMANCE_SCHEMA="pulsar-v14-performance-v5"
STRICT_CALIBRATION_SCHEMA="pulsar-v14-calibration-v2"
STRICT_PAPER_SCHEMA_PREFIX="pulsar-v14-paper-bet-performance-v"


def _load(path:Path|str)->dict[str,Any]:
    target=Path(path)
    if not target.exists(): return {}
    try: row=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {}
    return row if isinstance(row,dict) else {}


def _dt(value:Any)->datetime|None:
    if not value:return None
    try:
        out=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:return None


def _evidence_age_hours(payload:dict[str,Any],now:datetime)->float|None:
    generated=_dt(payload.get("generated_at"))
    if generated is None:return None
    return (now-generated).total_seconds()/3600.0


def _freshness_failure(payload:dict[str,Any],label:str,now:datetime)->str|None:
    age=_evidence_age_hours(payload,now)
    if age is None:return f"{label}_generated_at_missing_or_invalid"
    if age<-(MAX_FUTURE_SKEW_MINUTES/60.0):return f"{label}_generated_at_in_future"
    if age>MAX_EVIDENCE_AGE_HOURS:return f"{label}_evidence_stale>{MAX_EVIDENCE_AGE_HOURS:.0f}h"
    return None


def _calibration_accepted(calibrator:dict[str,Any])->bool:return calibrator.get("accepted") is True or calibrator.get("active") is True


def _paper_for_market(paper:dict[str,Any],market:str)->dict[str,Any]:
    scoped=((paper.get("by_market") or {}).get(market) or {});return (scoped.get("clv") or scoped) if scoped else {}


def _drift_failures(performance:dict[str,Any],market:str)->list[str]:
    rolling=(((performance.get("segments") or {}).get("rolling") or {}).get("60d") or {});metrics=(rolling.get("markets") or {}).get(market) or {}
    if int(metrics.get("n") or 0)<MIN_ROLLING_N:return []
    failures=[];ece=metrics.get("ece")
    if ece is not None and float(ece)>MAX_ROLLING_ECE:failures.append("rolling_60d_calibration_drift")
    sharp=metrics.get("sharp_benchmark") or {};paired=int(sharp.get("paired_n") or 0);lower=sharp.get("brier_gain_ci95_lower")
    if paired>=MIN_ROLLING_N and lower is not None and float(lower)<-.002:failures.append("rolling_60d_sharp_regression")
    return failures


def _sharp_failures(sharp:dict[str,Any])->list[str]:
    failures=[];paired=int(sharp.get("paired_n") or 0)
    if paired<MIN_PAIRED_SHARP_N:return [f"sharp_paired_n<{MIN_PAIRED_SHARP_N}"]
    b_lower=sharp.get("brier_gain_ci95_lower");l_lower=sharp.get("logloss_gain_ci95_lower")
    if b_lower is None or float(b_lower)<=0:failures.append("paired_brier_gain_ci95_not_positive")
    if l_lower is None or float(l_lower)<-.001:failures.append("paired_logloss_ci95_regression")
    return failures


def evaluate(performance:dict[str,Any]|None=None,calibration:dict[str,Any]|None=None,paper_performance:dict[str,Any]|None=None,*,now:datetime|None=None)->dict[str,Any]:
    perf=performance or {};cal=calibration or {};paper=_load(PAPER_PERFORMANCE) if paper_performance is None else paper_performance
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc)
    games=int(perf.get("games_settled") or 0);global_probability_reasons=[]
    if perf.get("schema")!=STRICT_PERFORMANCE_SCHEMA:global_probability_reasons.append("strict_performance_schema_required")
    if perf.get("model_generation")!=MODEL_GENERATION:global_probability_reasons.append("generation_mismatch")
    if cal.get("schema")!=STRICT_CALIBRATION_SCHEMA:global_probability_reasons.append("strict_calibration_schema_required")
    if cal.get("model_generation")!=MODEL_GENERATION:global_probability_reasons.append("calibration_generation_mismatch")
    for payload,label in ((perf,"performance"),(cal,"calibration")):
        failure=_freshness_failure(payload,label,current)
        if failure:global_probability_reasons.append(failure)
    if games<MIN_GAMES:global_probability_reasons.append(f"games_settled<{MIN_GAMES}")
    strict_paper=bool(str(paper.get("schema") or "").startswith(STRICT_PAPER_SCHEMA_PREFIX) and paper.get("by_market") is not None and paper.get("model_generation")==MODEL_GENERATION)
    paper_freshness=_freshness_failure(paper,"paper",current) if strict_paper else None

    perf_markets=perf.get("markets") or {};calibrators=cal.get("calibrators") or {};market_status={};any_probability=False;any_betting=False
    for market in MARKETS:
        metrics=perf_markets.get(market) or {};failures=list(global_probability_reasons);n=int(metrics.get("n") or 0);ece=metrics.get("ece")
        if n<MIN_MARKET_N:failures.append(f"n<{MIN_MARKET_N}")
        if ece is None or float(ece)>MAX_ECE:failures.append(f"ece>{MAX_ECE:.2f}_or_missing")
        calibrator=calibrators.get(f"MARKET:{market}") or {}
        if not _calibration_accepted(calibrator):failures.append("calibration_not_oos_accepted")
        failures.extend(_sharp_failures(metrics.get("sharp_benchmark") or {}));failures.extend(_drift_failures(perf,market));probability_certified=not failures;any_probability=any_probability or probability_certified

        betting_failures=list(failures)
        if not strict_paper:betting_failures.append("strict_current_generation_market_specific_paper_schema_required")
        elif paper_freshness:betting_failures.append(paper_freshness)
        clv=_paper_for_market(paper,market) if strict_paper else {};clv_n=int(clv.get("n") or 0);mean=clv.get("mean_clv");positive=clv.get("positive_rate");ci=clv.get("mean_clv_ci95_lower")
        if clv_n<MIN_PAPER_CLV_N:betting_failures.append(f"paper_clv_n<{MIN_PAPER_CLV_N}")
        if mean is None or float(mean)<=0:betting_failures.append("paper_mean_clv_not_positive")
        if positive is None or float(positive)<MIN_POSITIVE_CLV_RATE:betting_failures.append(f"paper_positive_clv_rate<{MIN_POSITIVE_CLV_RATE:.2f}")
        if ci is None:betting_failures.append("paper_clv_ci95_missing")
        elif float(ci)<=0:betting_failures.append("paper_clv_ci95_not_positive")
        betting_certified=probability_certified and not betting_failures;any_betting=any_betting or betting_certified
        market_status[market]={"probability_certified":probability_certified,"betting_certified":betting_certified,"probability_status":"PROBABILITY_CERTIFIED" if probability_certified else "PROBABILITY_RESEARCH","betting_status":"BETTING_CERTIFIED" if betting_certified else "RESEARCH_ONLY","n":n,"ece":ece,"calibration_status":calibrator.get("status"),"failures":failures,"betting_failures":betting_failures,"paper_clv":{"n":clv_n,"mean_clv":mean,"positive_rate":positive,"mean_clv_ci95_lower":ci}}

    probability_reasons=sorted({reason for row in market_status.values() for reason in row["failures"]}) if not any_probability else []
    betting_reasons=sorted({reason for row in market_status.values() for reason in row["betting_failures"]}) if not any_betting else []
    return {"schema":"pulsar-v14-betting-certification-v7","model_generation":MODEL_GENERATION,"software_role":"PRODUCTION","generated_at":current.isoformat(),"probability_status":"PROBABILITY_CERTIFIED" if any_probability else "PROBABILITY_RESEARCH","probability_certified":any_probability,"betting_status":"BETTING_CERTIFIED" if any_betting else "RESEARCH_ONLY","certified":any_betting,"markets":market_status,"probability_reasons":probability_reasons,"reasons":betting_reasons,"paired_inference_required":True,"paper_ci_required":True,"legacy_evidence_can_certify":False,"paper_clv":paper.get("clv") or {},"evidence_age_hours":{"performance":_evidence_age_hours(perf,current),"calibration":_evidence_age_hours(cal,current),"paper":_evidence_age_hours(paper,current)},"policy":{"strict_performance_schema":STRICT_PERFORMANCE_SCHEMA,"strict_calibration_schema":STRICT_CALIBRATION_SCHEMA,"exact_model_generation_required":True,"max_evidence_age_hours":MAX_EVIDENCE_AGE_HOURS,"min_games":MIN_GAMES,"min_market_n":MIN_MARKET_N,"max_ece":MAX_ECE,"min_paired_sharp_n":MIN_PAIRED_SHARP_N,"min_paper_clv_n":MIN_PAPER_CLV_N,"min_positive_clv_rate":MIN_POSITIVE_CLV_RATE,"market_specific_authorization":True,"rolling_drift_window_days":60,"paper_market_specific":True,"paper_independent_observations_required":True}}


def load_status(performance_path:Path|str=PERFORMANCE,calibration_path:Path|str=CALIBRATION,paper_path:Path|str=PAPER_PERFORMANCE)->dict[str,Any]:return evaluate(_load(performance_path),_load(calibration_path),_load(paper_path))
