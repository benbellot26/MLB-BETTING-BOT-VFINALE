from __future__ import annotations

"""Strict statistical betting certification, separate from software PRODUCTION.

Only current-generation, current-probability-policy, fresh, strict-schema
evidence can authorize betting. Legacy or stale reports remain diagnostic only.
Certification is market-specific and requires accepted calibration, paired
superiority to sharp, drift control, recent underlying observations, and
immutable prospective paper CLV measured from executable entry prices to
verified sharp and same-book closes.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID

PERFORMANCE=Path("data/v14_performance.json")
CALIBRATION=Path("data/v14_calibration.json")
PAPER_PERFORMANCE=Path("data/v14_paper_bet_performance.json")
MIN_GAMES=600
MIN_MARKET_N=400
MAX_ECE=.05
MIN_PAIRED_SHARP_N=400
MIN_PAPER_CLV_N=100
MIN_EXECUTION_CLV_N=50
MIN_POSITIVE_CLV_RATE=.52
MAX_ROLLING_ECE=.07
MIN_ROLLING_N=100
MAX_EVIDENCE_AGE_HOURS=48.0
MAX_OBSERVATION_AGE_HOURS=72.0
MAX_PAPER_CLOSE_AGE_HOURS=72.0
MAX_FUTURE_SKEW_MINUTES=10.0
MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")
STRICT_PERFORMANCE_SCHEMA="pulsar-v14-performance-v5"
STRICT_CALIBRATION_SCHEMA="pulsar-v14-calibration-v3"
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


def _age_hours(value:Any,now:datetime)->float|None:
    observed=_dt(value)
    return (now-observed).total_seconds()/3600.0 if observed is not None else None


def _evidence_age_hours(payload:dict[str,Any],now:datetime)->float|None:
    return _age_hours(payload.get("generated_at"),now)


def _freshness_failure(payload:dict[str,Any],label:str,now:datetime)->str|None:
    age=_evidence_age_hours(payload,now)
    if age is None:return f"{label}_generated_at_missing_or_invalid"
    if age<-(MAX_FUTURE_SKEW_MINUTES/60.0):return f"{label}_generated_at_in_future"
    if age>MAX_EVIDENCE_AGE_HOURS:return f"{label}_evidence_stale>{MAX_EVIDENCE_AGE_HOURS:.0f}h"
    return None


def _latest_performance_observation(performance:dict[str,Any])->str|None:
    direct=performance.get("latest_observation_at")
    if _dt(direct) is not None:return str(direct)
    rolling=(((performance.get("segments") or {}).get("rolling") or {})); candidates=[]
    for row in rolling.values():
        value=(row or {}).get("through")
        parsed=_dt(value)
        if parsed is not None:candidates.append((parsed,str(value)))
    return max(candidates,key=lambda item:item[0])[1] if candidates else None


def _timestamp_freshness_failure(value:Any,label:str,now:datetime,max_age_hours:float)->str|None:
    age=_age_hours(value,now)
    if age is None:return f"{label}_missing_or_invalid"
    if age<-(MAX_FUTURE_SKEW_MINUTES/60.0):return f"{label}_in_future"
    if age>max_age_hours:return f"{label}_stale>{max_age_hours:.0f}h"
    return None


def _calibration_accepted(calibrator:dict[str,Any])->bool:return calibrator.get("accepted") is True or calibrator.get("active") is True


def _paper_scope(paper:dict[str,Any],market:str)->dict[str,Any]:
    return ((paper.get("by_market") or {}).get(market) or {})


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


def _clv_failures(clv:dict[str,Any],*,minimum_n:int,prefix:str,positive_rate_required:bool)->list[str]:
    failures=[]; n=int(clv.get("n") or 0); mean=clv.get("mean_clv"); ci=clv.get("mean_clv_ci95_lower")
    if n<minimum_n:failures.append(f"{prefix}_n<{minimum_n}")
    if mean is None or float(mean)<=0:failures.append(f"{prefix}_mean_not_positive")
    if positive_rate_required:
        positive=clv.get("positive_rate")
        if positive is None or float(positive)<MIN_POSITIVE_CLV_RATE:failures.append(f"{prefix}_positive_rate<{MIN_POSITIVE_CLV_RATE:.2f}")
    if ci is None:failures.append(f"{prefix}_ci95_missing")
    elif float(ci)<=0:failures.append(f"{prefix}_ci95_not_positive")
    return failures


def evaluate(performance:dict[str,Any]|None=None,calibration:dict[str,Any]|None=None,paper_performance:dict[str,Any]|None=None,*,now:datetime|None=None)->dict[str,Any]:
    perf=performance or {};cal=calibration or {};paper=_load(PAPER_PERFORMANCE) if paper_performance is None else paper_performance
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc)
    games=int(perf.get("games_settled") or 0);global_probability_reasons=[]
    if perf.get("schema")!=STRICT_PERFORMANCE_SCHEMA:global_probability_reasons.append("strict_performance_schema_required")
    if perf.get("model_generation")!=MODEL_GENERATION:global_probability_reasons.append("generation_mismatch")
    if perf.get("probability_policy_id")!=PROBABILITY_POLICY_ID:global_probability_reasons.append("performance_probability_policy_mismatch")
    if cal.get("schema")!=STRICT_CALIBRATION_SCHEMA:global_probability_reasons.append("strict_calibration_schema_required")
    if cal.get("model_generation")!=MODEL_GENERATION:global_probability_reasons.append("calibration_generation_mismatch")
    if cal.get("probability_policy_id")!=PROBABILITY_POLICY_ID:global_probability_reasons.append("calibration_probability_policy_mismatch")
    for payload,label in ((perf,"performance"),(cal,"calibration")):
        failure=_freshness_failure(payload,label,current)
        if failure:global_probability_reasons.append(failure)
    observation_at=_latest_performance_observation(perf); observation_failure=_timestamp_freshness_failure(observation_at,"latest_performance_observation",current,MAX_OBSERVATION_AGE_HOURS)
    if observation_failure:global_probability_reasons.append(observation_failure)
    calibration_observation=cal.get("latest_observation_at"); calibration_observation_failure=_timestamp_freshness_failure(calibration_observation,"latest_calibration_observation",current,MAX_OBSERVATION_AGE_HOURS)
    if calibration_observation_failure:global_probability_reasons.append(calibration_observation_failure)
    if games<MIN_GAMES:global_probability_reasons.append(f"games_settled<{MIN_GAMES}")
    strict_paper=bool(str(paper.get("schema") or "").startswith(STRICT_PAPER_SCHEMA_PREFIX) and paper.get("by_market") is not None and paper.get("model_generation")==MODEL_GENERATION and paper.get("probability_policy_id")==PROBABILITY_POLICY_ID)
    paper_freshness=_freshness_failure(paper,"paper",current) if strict_paper else None

    perf_markets=perf.get("markets") or {};calibrators=cal.get("calibrators") or {};market_status={};any_probability=False;any_betting=False
    for market in MARKETS:
        metrics=perf_markets.get(market) or {};failures=list(global_probability_reasons);n=int(metrics.get("n") or 0);ece=metrics.get("ece")
        if n<MIN_MARKET_N:failures.append(f"n<{MIN_MARKET_N}")
        if ece is None or float(ece)>MAX_ECE:failures.append(f"ece>{MAX_ECE:.2f}_or_missing")
        calibrator=calibrators.get(f"MARKET:{market}") or {}
        if not _calibration_accepted(calibrator):failures.append("calibration_not_oos_accepted")
        failures.extend(_sharp_failures(metrics.get("sharp_benchmark") or {}));failures.extend(_drift_failures(perf,market));probability_certified=not failures;any_probability=any_probability or probability_certified

        betting_failures=list(failures); scope=_paper_scope(paper,market) if strict_paper else {}
        if not strict_paper:betting_failures.append("strict_current_generation_policy_market_specific_paper_schema_required")
        elif paper_freshness:betting_failures.append(paper_freshness)
        if strict_paper:
            close_failure=_timestamp_freshness_failure(scope.get("latest_certified_close_at"),f"{market}_latest_certified_close",current,MAX_PAPER_CLOSE_AGE_HOURS)
            if close_failure:betting_failures.append(close_failure)
        primary=scope.get("certification_clv") or {}; execution=scope.get("execution_clv") or {}
        betting_failures.extend(_clv_failures(primary,minimum_n=MIN_PAPER_CLV_N,prefix="paper_certification_clv",positive_rate_required=True))
        betting_failures.extend(_clv_failures(execution,minimum_n=MIN_EXECUTION_CLV_N,prefix="paper_execution_clv",positive_rate_required=False))
        betting_certified=probability_certified and not betting_failures;any_betting=any_betting or betting_certified
        market_status[market]={"probability_certified":probability_certified,"betting_certified":betting_certified,"probability_status":"PROBABILITY_CERTIFIED" if probability_certified else "PROBABILITY_RESEARCH","betting_status":"BETTING_CERTIFIED" if betting_certified else "RESEARCH_ONLY","n":n,"ece":ece,"calibration_status":calibrator.get("status"),"failures":failures,"betting_failures":betting_failures,"paper_certification_clv":primary,"paper_execution_clv":execution,"paper_latest_certified_close_at":scope.get("latest_certified_close_at")}

    probability_reasons=sorted({reason for row in market_status.values() for reason in row["failures"]}) if not any_probability else []
    betting_reasons=sorted({reason for row in market_status.values() for reason in row["betting_failures"]}) if not any_betting else []
    return {"schema":"pulsar-v14-betting-certification-v9","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"software_role":"PRODUCTION","generated_at":current.isoformat(),"probability_status":"PROBABILITY_CERTIFIED" if any_probability else "PROBABILITY_RESEARCH","probability_certified":any_probability,"betting_status":"BETTING_CERTIFIED" if any_betting else "RESEARCH_ONLY","certified":any_betting,"markets":market_status,"probability_reasons":probability_reasons,"reasons":betting_reasons,"paired_inference_required":True,"paper_ci_required":True,"legacy_evidence_can_certify":False,"paper_clv":paper.get("certification_clv") or {},"paper_execution_clv":paper.get("execution_clv") or {},"evidence_age_hours":{"performance_report":_evidence_age_hours(perf,current),"performance_observation":_age_hours(observation_at,current),"calibration_report":_evidence_age_hours(cal,current),"calibration_observation":_age_hours(calibration_observation,current),"paper_report":_evidence_age_hours(paper,current)},"policy":{"strict_performance_schema":STRICT_PERFORMANCE_SCHEMA,"strict_calibration_schema":STRICT_CALIBRATION_SCHEMA,"exact_model_generation_required":True,"exact_probability_policy_required_for_performance_calibration_and_paper":True,"max_evidence_age_hours":MAX_EVIDENCE_AGE_HOURS,"max_observation_age_hours":MAX_OBSERVATION_AGE_HOURS,"max_paper_close_age_hours":MAX_PAPER_CLOSE_AGE_HOURS,"min_games":MIN_GAMES,"min_market_n":MIN_MARKET_N,"max_ece":MAX_ECE,"min_paired_sharp_n":MIN_PAIRED_SHARP_N,"min_paper_certification_clv_n":MIN_PAPER_CLV_N,"min_paper_execution_clv_n":MIN_EXECUTION_CLV_N,"min_positive_clv_rate":MIN_POSITIVE_CLV_RATE,"market_specific_authorization":True,"rolling_drift_window_days":60,"paper_market_specific":True,"paper_independent_observations_required":True,"primary_clv_definition":"entry executable implied probability to verified no-vig sharp fair close","secondary_clv_definition":"entry executable implied probability to fresh same-book close"}}


def load_status(performance_path:Path|str=PERFORMANCE,calibration_path:Path|str=CALIBRATION,paper_path:Path|str=PAPER_PERFORMANCE)->dict[str,Any]:return evaluate(_load(performance_path),_load(calibration_path),_load(paper_path))
