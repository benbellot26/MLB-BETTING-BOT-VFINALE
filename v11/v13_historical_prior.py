from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import calibration_baseball_v13 as calibration
from .distribution_learning_v13 import estimate_negative_binomial_dispersion, estimate_shared_environment_sigma
from .v13_reconstruct_1801 import build as reconstruct_build

MODEL_FILE = Path("data/v13_historical_prior.json")
SCHEMA = "v13-historical-prior-v1"
DEFAULT_DISPERSION = 7.5
DEFAULT_ENV_SIGMA = .08
MIN_TEST_GAMES = 250
BOOTSTRAP_DRAWS = 1200


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _day(row: dict[str, Any]) -> str:
    return str(row.get("game_date") or "")[:10]


def _split_days(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    days = sorted({_day(r) for r in rows})
    n = len(days)
    a = max(1, int(n * .60)); b = max(a + 1, int(n * .80))
    train_days, val_days, test_days = set(days[:a]), set(days[a:b]), set(days[b:])
    return ([r for r in rows if _day(r) in train_days],
            [r for r in rows if _day(r) in val_days],
            [r for r in rows if _day(r) in test_days])


def _examples(rows: list[dict[str, Any]], market: str) -> list[tuple[float, int, str]]:
    out = []
    for r in rows:
        for o in r.get("options") or []:
            if o.get("market") != market or not o.get("calibration_trainable"):
                continue
            if o.get("result") not in {"WIN", "LOSS"} or o.get("p_baseball_raw") is None:
                continue
            out.append((float(o["p_baseball_raw"]), 1 if o["result"] == "WIN" else 0, _day(r)))
    return out


def _metrics(examples: list[tuple[float,int,str]], params: dict[str,Any] | None = None) -> dict[str,Any]:
    if not examples:
        return {"n": 0, "brier": None, "logloss": None, "ece": None}
    vals = []
    for p,y,d in examples:
        q = calibration._apply(params or {"method":"identity"}, p)
        vals.append((q,y,d))
    n = len(vals)
    brier = sum((p-y)**2 for p,y,_ in vals)/n
    ll = -sum(y*math.log(max(.001,p))+(1-y)*math.log(max(.001,1-p)) for p,y,_ in vals)/n
    ece = 0.0
    for lo,hi in ((0,.45),(.45,.50),(.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,1.001)):
        z=[(p,y) for p,y,_ in vals if lo <= p < hi]
        if z:
            ece += len(z)/n*abs(sum(p for p,_ in z)/len(z)-sum(y for _,y in z)/len(z))
    return {"n":n,"brier":brier,"logloss":ll,"ece":ece}


def _paired_day_bootstrap(identity: list[tuple[float,int,str]], params: dict[str,Any]) -> dict[str,Any]:
    by_day: dict[str,list[tuple[float,int]]] = defaultdict(list)
    for p,y,d in identity:
        by_day[d].append((p,y))
    days = sorted(by_day)
    if len(days) < 10:
        return {"draws":0,"brier_gain_ci95":[None,None],"positive":False}
    rng = random.Random(13013)
    gains=[]
    for _ in range(BOOTSTRAP_DRAWS):
        sample=[rng.choice(days) for _ in days]
        base=[]; cand=[]
        for d in sample:
            for p,y in by_day[d]:
                base.append((p-y)**2)
                q=calibration._apply(params,p)
                cand.append((q-y)**2)
        gains.append(sum(base)/len(base)-sum(cand)/len(cand))
    gains.sort()
    lo=gains[int(.025*(len(gains)-1))]; hi=gains[int(.975*(len(gains)-1))]
    return {"draws":len(gains),"brier_gain_ci95":[lo,hi],"positive":lo>0}


def _calibration_market(train: list[dict[str,Any]], val: list[dict[str,Any]], test: list[dict[str,Any]], market: str) -> dict[str,Any]:
    tr=_examples(train,market); va=_examples(val,market); te=_examples(test,market)
    # Stage 1: method discovery on historical train only.
    discovered=calibration.fit_calibrator([(p,y) for p,y,_ in tr], max(180, min(400, len(tr)//2)))
    params1={k:v for k,v in discovered.items() if k in {"method","a","b","c"}}
    val_base=_metrics(va); val_cand=_metrics(va,params1)
    val_pass=(discovered.get("active") and val_cand["brier"] < val_base["brier"] and val_cand["logloss"] <= val_base["logloss"] and val_cand["ece"] <= val_base["ece"]+.003)

    # Stage 2: freeze a train+validation model, then score untouched future dates.
    train_val=tr+va
    final_fit=calibration.fit_calibrator([(p,y) for p,y,_ in train_val], max(240, min(600, len(train_val)//2))) if val_pass else {"active":False,"method":"identity","n":len(train_val)}
    params2={k:v for k,v in final_fit.items() if k in {"method","a","b","c"}}
    test_base=_metrics(te); test_cand=_metrics(te,params2)
    boot=_paired_day_bootstrap(te,params2)
    test_pass=(bool(final_fit.get("active")) and len(te)>=MIN_TEST_GAMES and test_cand["brier"] < test_base["brier"] and test_cand["logloss"] <= test_base["logloss"] and test_cand["ece"] <= test_base["ece"]+.003 and boot["positive"])
    return {
        "market":market,"train_n":len(tr),"validation_n":len(va),"test_n":len(te),
        "discovery_fit":discovered,"validation":{"identity":val_base,"candidate":val_cand,"passes":val_pass},
        "frozen_fit":final_fit,"test":{"identity":test_base,"candidate":test_cand,"bootstrap":boot,"passes":test_pass},
        "historically_validated":bool(val_pass and test_pass),
        "active_for_v13_live":False,
        "live_transfer_status":"COLLECTING_EXACT_V13_TRANSFER_EVIDENCE",
        "live_transfer_reason":"Historical probabilities are V10 FINAL walk-forward outputs, not the current V13 raw probability contract.",
    }


def _nb_logpmf(mu: float, y: int, dispersion: float) -> float:
    r=max(.5,dispersion); mu=max(.01,mu); p=r/(r+mu)
    return math.lgamma(y+r)-math.lgamma(r)-math.lgamma(y+1)+r*math.log(p)+y*math.log1p(-p)


def _env_nodes(sigma: float):
    sigma=max(0.0,min(.30,sigma))
    if sigma <= 1e-12: return [(1.0,1.0)]
    d=math.sqrt(3)*sigma
    return [(max(.45,1-d),1/6),(1.0,2/3),(1+d,1/6)]


def _joint_nll(rows: list[dict[str,Any]], dispersion: float, sigma: float) -> float:
    vals=[]
    for r in rows:
        hmu,amu=r.get("projected_home_runs"),r.get("projected_away_runs")
        if hmu is None or amu is None: continue
        hs,aws=int(r["home_score"]),int(r["away_score"])
        prob=0.0
        for f,w in _env_nodes(sigma):
            prob += w*math.exp(_nb_logpmf(_num(hmu)*f,hs,dispersion)+_nb_logpmf(_num(amu)*f,aws,dispersion))
        vals.append(-math.log(max(1e-15,prob)))
    return sum(vals)/len(vals) if vals else 999.0


def _distribution_prior(train: list[dict[str,Any]], val: list[dict[str,Any]], test: list[dict[str,Any]]) -> dict[str,Any]:
    d1=estimate_negative_binomial_dispersion(train,DEFAULT_DISPERSION); s1=estimate_shared_environment_sigma(train,DEFAULT_ENV_SIGMA)
    vb=_joint_nll(val,DEFAULT_DISPERSION,DEFAULT_ENV_SIGMA); vc=_joint_nll(val,d1,s1)
    val_pass=vc < vb-.0005
    tv=train+val
    d2=estimate_negative_binomial_dispersion(tv,DEFAULT_DISPERSION); s2=estimate_shared_environment_sigma(tv,DEFAULT_ENV_SIGMA)
    tb=_joint_nll(test,DEFAULT_DISPERSION,DEFAULT_ENV_SIGMA); tc=_joint_nll(test,d2,s2)
    test_pass=len(test)>=MIN_TEST_GAMES and tc < tb-.0005
    return {
        "candidate":{"dispersion":d2,"environment_sigma":s2},
        "validation":{"games":len(val),"default_nll":vb,"candidate_nll":vc,"gain":vb-vc,"passes":val_pass},
        "test":{"games":len(test),"default_nll":tb,"candidate_nll":tc,"gain":tb-tc,"passes":test_pass},
        "historically_validated":bool(val_pass and test_pass),
        "active_for_v13_score_distribution":bool(val_pass and test_pass),
        "scope":"Generic run-count distribution prior; no market data used.",
    }


def build() -> dict[str,Any]:
    rows,_=reconstruct_build()
    warm=[r for r in rows if r.get("warm_sample")]
    train,val,test=_split_days(warm)
    model={
        "schema":SCHEMA,"generated_at":datetime.now(timezone.utc).isoformat(),
        "source_games":len(rows),"warm_games":len(warm),
        "split":{"train_games":len(train),"validation_games":len(val),"test_games":len(test),
                 "train_end":max((_day(r) for r in train),default=None),"validation_end":max((_day(r) for r in val),default=None),"test_end":max((_day(r) for r in test),default=None),"grouped_by_day":True},
        "calibration":{"ML":_calibration_market(train,val,test,"ML"),"RUNLINE":_calibration_market(train,val,test,"RUNLINE")},
        "distribution":_distribution_prior(train,val,test),
        "safety":{"historical_odds_used":False,"market_probability_as_feature":False,"totals_live_calibration":False,
                  "historical_calibration_auto_promoted_to_live":False,"exact_v13_transfer_gate_required":True},
    }
    return model


def main() -> None:
    model=build(); MODEL_FILE.parent.mkdir(parents=True,exist_ok=True)
    MODEL_FILE.write_text(json.dumps(model,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(model,ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__": main()
