from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import v13_daily_tracking as tracking

OUT = Path("data/v13_probability_diagnostics.json")
SCHEMA = "v13-probability-diagnostics-v1"


def _num(v: Any, d: float | None = None) -> float | None:
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _gap_bin(gap: float) -> str:
    pp=100*gap
    if pp < -10:return "<-10pp"
    if pp < -6:return "-10/-6pp"
    if pp < -3:return "-6/-3pp"
    if pp < 0:return "-3/0pp"
    if pp < 3:return "0/3pp"
    if pp < 6:return "3/6pp"
    if pp < 10:return "6/10pp"
    return ">=10pp"


def _canonical_side(s: dict[str,Any]) -> bool:
    market=str(s.get("market") or "").upper();pick=str(s.get("pick") or "");home=str(s.get("home") or "")
    if market=="ML":return _norm(pick)==_norm(home)
    if market=="RUNLINE":return bool(s.get("canonical")) and _norm(pick)==_norm(home)
    if market=="TOTAL":return bool(s.get("canonical")) and pick.lower()=="over"
    return False


def _rank(s: dict[str,Any]) -> tuple[int,str]:
    phase={"EARLY":0,"LATE":1,"FINAL":2}.get(str(s.get("phase") or s.get("observation_phase") or "").upper(),-1)
    return phase,str(s.get("observation_at") or s.get("observed_at") or "")


def independent_states(states: list[dict[str,Any]]) -> list[dict[str,Any]]:
    best={}
    for s in states:
        if s.get("settled_result") not in {"WIN","LOSS"}:continue
        if not _canonical_side(s):continue
        if _num(s.get("p_model")) is None or _num(s.get("p_market")) is None:continue
        key=(str(s.get("game_pk") or ""),str(s.get("market") or "").upper())
        if not key[0]:continue
        if key not in best or _rank(s)>_rank(best[key]):best[key]=s
    return sorted(best.values(),key=lambda s:(str(s.get("game_date") or ""),str(s.get("game_pk") or ""),str(s.get("market") or "")))


def _metrics(rows: list[dict[str,Any]]) -> dict[str,Any]:
    if not rows:return {"n":0}
    b_model=b_market=ll_model=ll_market=0.0;residuals=[];gaps=[]
    for s in rows:
        pm=max(.001,min(.999,float(s["p_model"])));ps=max(.001,min(.999,float(s["p_market"])))
        y=1 if s.get("settled_result")=="WIN" else 0;gap=pm-ps
        b_model+=(pm-y)**2;b_market+=(ps-y)**2
        ll_model+=-(y*math.log(pm)+(1-y)*math.log(1-pm));ll_market+=-(y*math.log(ps)+(1-y)*math.log(1-ps))
        residuals.append(y-ps);gaps.append(gap)
    n=len(rows);mean_gap=sum(gaps)/n;mean_res=sum(residuals)/n;var=sum((x-mean_gap)**2 for x in gaps)
    slope=(sum((x-mean_gap)*(y-mean_res) for x,y in zip(gaps,residuals))/var) if var>1e-12 else None
    return {"n":n,"model_brier":b_model/n,"market_brier":b_market/n,"brier_gain_vs_market":(b_market-b_model)/n,
            "model_logloss":ll_model/n,"market_logloss":ll_market/n,"logloss_gain_vs_market":(ll_market-ll_model)/n,
            "mean_model_minus_market":mean_gap,"outcome_residual_vs_market":mean_res,"gap_residual_slope":slope}


def build(states: list[dict[str,Any]] | None = None) -> dict[str,Any]:
    folded=list(tracking.fold().values()) if states is None else list(states);rows=independent_states(folded)
    by_market={m:_metrics([r for r in rows if str(r.get("market") or "").upper()==m]) for m in ("ML","RUNLINE","TOTAL")}
    bins={}
    names=("<-10pp","-10/-6pp","-6/-3pp","-3/0pp","0/3pp","3/6pp","6/10pp",">=10pp")
    for market in ("ML","RUNLINE","TOTAL"):
        subset=[r for r in rows if str(r.get("market") or "").upper()==market]
        bins[market]={name:_metrics([r for r in subset if _gap_bin(float(r["p_model"])-float(r["p_market"]))==name]) for name in names}
    return {"schema":SCHEMA,"sample_unit":"unique game + market; latest canonical pregame snapshot",
            "independent_targets":len(rows),"by_market":by_market,"by_model_market_gap_bin":bins,
            "interpretation":{"gap_residual_slope":"positive is desirable: larger model-minus-market gaps should correspond to larger positive outcome residuals versus the market probability",
                              "proper_scoring":"Brier and LogLoss are the primary comparison; repeated phases and complementary sides are excluded from the independent view"}}


def main():
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":main()
