from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import v13_daily_tracking as tracking
from . import v138_advanced_research as calibration
from . import v138_book_telemetry as book_telemetry
from . import v138_validation as validation

OUT=Path("data/v138_native_evidence.json")
SCHEMA="v13-8-native-evidence-gates-v1"
MIN_NATIVE=300


def _num(v: Any,d: float | None=None) -> float | None:
    try:
        x=float(v);return x if math.isfinite(x) else d
    except Exception:return d


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _canonical_side(s: dict[str,Any]) -> bool:
    market=str(s.get("market") or "").upper();pick=str(s.get("pick") or "");home=str(s.get("home") or "")
    if market=="ML":return _norm(pick)==_norm(home)
    if market=="RUNLINE":return bool(s.get("canonical")) and _norm(pick)==_norm(home)
    if market=="TOTAL":return bool(s.get("canonical")) and pick.lower()=="over"
    return False


def _rank(s: dict[str,Any]) -> tuple[int,str]:
    phase={"EARLY":0,"LATE":1,"FINAL":2}.get(str(s.get("phase") or s.get("observation_phase") or "").upper(),-1)
    return phase,str(s.get("observation_at") or s.get("observed_at") or "")


def independent_settled(states: list[dict[str,Any]] | None=None) -> list[dict[str,Any]]:
    folded=list(tracking.fold().values()) if states is None else list(states);best={}
    for s in folded:
        if s.get("settled_result") not in {"WIN","LOSS"}:continue
        if not _canonical_side(s):continue
        if _num(s.get("p_model")) is None:continue
        key=(str(s.get("game_pk") or ""),str(s.get("market") or "").upper())
        if not key[0]:continue
        if key not in best or _rank(s)>_rank(best[key]):best[key]=s
    return sorted(best.values(),key=lambda s:(str(s.get("game_date") or ""),str(s.get("game_pk") or ""),str(s.get("market") or "")))


def _outcome(s: dict[str,Any]) -> int:
    return 1 if s.get("settled_result")=="WIN" else 0


def probability_band_validation(rows: list[dict[str,Any]],min_n: int=MIN_NATIVE,min_bin: int=30) -> dict[str,Any]:
    """Validate model-probability uncertainty bands against grouped empirical rates.

    Binary outcomes cannot meaningfully be checked one-by-one against a
    probability interval. Instead, independent targets are grouped into fixed
    5pp probability bins; each bin's empirical win rate is compared with the
    mean model interval. This validates calibration-scale coverage without
    pretending the interval is a frequentist confidence interval for outcomes.
    """
    usable=[r for r in rows if _num(r.get("probability_interval_low")) is not None and _num(r.get("probability_interval_high")) is not None]
    bins={}
    for r in usable:
        p=max(.001,min(.999,float(r["p_model"])));idx=min(19,int(p/.05));bins.setdefault(idx,[]).append(r)
    details=[];weighted_inside=0;weighted_total=0;weighted_abs_error=0.0;weighted_half_width=0.0
    for idx,xs in sorted(bins.items()):
        if len(xs)<min_bin:continue
        emp=sum(_outcome(x) for x in xs)/len(xs);pm=sum(float(x["p_model"]) for x in xs)/len(xs)
        lo=sum(float(x["probability_interval_low"]) for x in xs)/len(xs);hi=sum(float(x["probability_interval_high"]) for x in xs)/len(xs)
        inside=lo<=emp<=hi;n=len(xs);weighted_total+=n;weighted_inside+=n*int(inside)
        weighted_abs_error+=n*abs(emp-pm);weighted_half_width+=n*((hi-lo)/2.0)
        details.append({"bin_low":idx*.05,"bin_high":(idx+1)*.05,"n":n,"mean_probability":pm,"empirical_rate":emp,
                        "mean_interval_low":lo,"mean_interval_high":hi,"inside":inside})
    coverage=weighted_inside/weighted_total if weighted_total else None
    mae=weighted_abs_error/weighted_total if weighted_total else None
    half=weighted_half_width/weighted_total if weighted_total else None
    enough=len(usable)>=min_n and weighted_total>=min_n and len(details)>=5
    passed=bool(enough and coverage is not None and coverage>=.80 and mae is not None and half is not None and mae<=half)
    return {"active":passed,"n":len(usable),"evaluated_n":weighted_total,"minimum_n":min_n,"usable_bins":len(details),
            "weighted_bin_coverage":coverage,"calibration_mae":mae,"mean_interval_half_width":half,"bins":details,
            "criterion":">=300 independent targets, >=5 bins with n>=30, >=80% weighted empirical-rate coverage and calibration MAE <= mean half-width",
            "user_facing_type":"model_uncertainty_band","frequentist_confidence_interval":False}


def dynamic_calibration_oos(rows: list[dict[str,Any]],min_n: int=MIN_NATIVE) -> dict[str,Any]:
    usable=[r for r in rows if _num(r.get("p_model")) is not None]
    usable.sort(key=lambda r:str(r.get("game_date") or r.get("observation_at") or ""))
    if len(usable)<min_n:return {"active":False,"n":len(usable),"minimum_n":min_n,"reason":"INSUFFICIENT_NATIVE_TARGETS"}
    cut=max(200,int(len(usable)*.70));train=usable[:cut];test=usable[cut:]
    if len(test)<60:return {"active":False,"n":len(usable),"minimum_n":min_n,"reason":"INSUFFICIENT_OOS_HOLDOUT"}
    p_train=[float(x["p_model"]) for x in train];y_train=[_outcome(x) for x in train]
    model=calibration.fit_platt(p_train,y_train)
    if not model.get("active"):return {"active":False,"n":len(usable),"train_n":len(train),"holdout_n":len(test),"reason":"CALIBRATOR_NOT_FIT"}
    raw=[max(.001,min(.999,float(x["p_model"]))) for x in test];y=[_outcome(x) for x in test]
    cal=[calibration.apply_platt(model,p) for p in raw]
    raw_b=validation.brier(y,raw);cal_b=validation.brier(y,cal);raw_ll=validation.logloss(y,raw);cal_ll=validation.logloss(y,cal)
    passed=bool(cal_b is not None and raw_b is not None and cal_ll is not None and raw_ll is not None and cal_b<=raw_b and cal_ll<raw_ll)
    return {"active":passed,"n":len(usable),"minimum_n":min_n,"train_n":len(train),"holdout_n":len(test),
            "calibrator":model,"raw_brier":raw_b,"calibrated_brier":cal_b,"raw_logloss":raw_ll,"calibrated_logloss":cal_ll,
            "brier_gain":None if raw_b is None or cal_b is None else raw_b-cal_b,
            "logloss_gain":None if raw_ll is None or cal_ll is None else raw_ll-cal_ll,
            "criterion":"chronological OOS holdout; calibrated Brier non-worse and LogLoss strictly better",
            "production_applied":False}


def _book_index(rows: list[dict[str,Any]]) -> dict[tuple[str,str],dict[str,Any]]:
    best={}
    for r in rows:
        if not r.get("canonical") or not (r.get("book_probs") or {}):continue
        key=(str(r.get("game_pk") or ""),str(r.get("market") or "").upper())
        if not key[0]:continue
        if key not in best or _rank(r)>_rank(best[key]):best[key]=r
    return best


def _weighted_book_probability(row: dict[str,Any],weights: dict[str,float]) -> float | None:
    probs=row.get("book_probs") or {};vals=[(float(weights[b]),float(probs[b])) for b in weights if probs.get(b) is not None]
    total=sum(w for w,_ in vals)
    return sum(w*p for w,p in vals)/total if total>0 else None


def bookmaker_weights_oos(states: list[dict[str,Any]],telemetry: list[dict[str,Any]],min_n: int=MIN_NATIVE) -> dict[str,Any]:
    idx=_book_index(telemetry);joined=[]
    for state in states:
        key=(str(state.get("game_pk") or ""),str(state.get("market") or "").upper());tele=idx.get(key)
        if not tele:continue
        probs=tele.get("book_probs") or {}
        if len(probs)<2:continue
        joined.append({"game_date":state.get("game_date"),"outcome":_outcome(state),"p_market":state.get("p_market"),"book_probs":probs})
    joined.sort(key=lambda r:str(r.get("game_date") or ""))
    if len(joined)<min_n:return {"active":False,"n":len(joined),"minimum_n":min_n,"reason":"INSUFFICIENT_PIT_BOOK_TARGETS"}
    cut=max(200,int(len(joined)*.70));train=joined[:cut];test=joined[cut:]
    if len(test)<60:return {"active":False,"n":len(joined),"minimum_n":min_n,"reason":"INSUFFICIENT_OOS_HOLDOUT"}
    learned=validation.learn_bookmaker_weights(train,min_games=min(200,len(train)))
    weights=learned.get("weights") or {}
    if not learned.get("active") or len(weights)<2:return {"active":False,"n":len(joined),"reason":"WEIGHTS_NOT_LEARNED"}
    y=[];pl=[];pb=[]
    for r in test:
        p=_weighted_book_probability(r,weights);base=_num(r.get("p_market"))
        if p is None or base is None:continue
        y.append(int(r["outcome"]));pl.append(max(.001,min(.999,p)));pb.append(max(.001,min(.999,float(base))))
    if len(y)<60:return {"active":False,"n":len(joined),"train_n":len(train),"holdout_n":len(y),"reason":"INSUFFICIENT_COMPARABLE_OOS_ROWS"}
    lb=validation.brier(y,pl);bb=validation.brier(y,pb);lll=validation.logloss(y,pl);bll=validation.logloss(y,pb)
    passed=bool(lb is not None and bb is not None and lll is not None and bll is not None and lb<=bb and lll<=bll)
    return {"active":passed,"n":len(joined),"minimum_n":min_n,"train_n":len(train),"holdout_n":len(y),"weights":weights,
            "learned_brier":lb,"configured_consensus_brier":bb,"learned_logloss":lll,"configured_consensus_logloss":bll,
            "brier_gain":None if lb is None or bb is None else bb-lb,"logloss_gain":None if lll is None or bll is None else bll-lll,
            "criterion":">=300 PIT canonical targets; chronological OOS learned weights must be non-worse on both Brier and LogLoss",
            "production_applied":False}


def build(states: list[dict[str,Any]] | None=None,telemetry: list[dict[str,Any]] | None=None) -> dict[str,Any]:
    rows=independent_settled(states);books=book_telemetry.read() if telemetry is None else list(telemetry)
    return {"schema":SCHEMA,"independent_native_targets":len(rows),
            "uncertainty_coverage":probability_band_validation(rows),
            "dynamic_calibration":dynamic_calibration_oos(rows),
            "bookmaker_weights":bookmaker_weights_oos(rows,books),
            "policy":"all gates use independent canonical settled pregame observations; OOS gates are chronological and never alter production automatically"}


def main() -> None:
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"schema":SCHEMA,"independent_native_targets":report["independent_native_targets"],
        "uncertainty_active":report["uncertainty_coverage"].get("active"),
        "book_weights_active":report["bookmaker_weights"].get("active"),
        "dynamic_calibration_active":report["dynamic_calibration"].get("active")},indent=2,sort_keys=True))


if __name__=="__main__":main()
