from __future__ import annotations

"""Conditional-variance research layer for V14 score distributions.

This module learns whether PIT uncertainty features explain residual variance.
That is only an intermediate research result: even a significant variance-target
fit is never promotion-eligible until a downstream score-distribution evaluation
proves better final-score NLL and market proper scores.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_heteroskedastic_candidate.json")
MIN_GAMES=700
MIN_HOLDOUT=120
FEATURES=("projected_total","starter_uncertainty","bullpen_stress","lineup_missing","weather_abs","park_deviation")


def _num(v:Any,d:float=0.0)->float:
    try: out=float(v)
    except Exception: return d
    return out if math.isfinite(out) else d


def vector(row:dict[str,Any])->list[float]|None:
    tf=row.get("training_features") or {}
    if tf.get("point_in_time") is not True: return None
    h=_num(row.get("home_mu"),4.4); a=_num(row.get("away_mu"),4.4); q=tf.get("data_quality") or {}; challengers=tf.get("research_challengers") or {}; hu=challengers.get("home_starter_usage") or {}; au=challengers.get("away_starter_usage") or {}; bullpen=tf.get("bullpen") or {}
    def stress(side:str)->float:
        rel=[x for x in ((bullpen.get(side) or {}).get("relievers") or []) if isinstance(x,dict)]; return sum(bool(x.get("taxed")) or bool(x.get("likely_unavailable")) for x in rel)/len(rel) if rel else 0.0
    starter_uncertainty=1-.5*(_num(hu.get("confidence"),0)+_num(au.get("confidence"),0)); lineup_missing=(18-int(q.get("home_lineup_count") or 0)-int(q.get("away_lineup_count") or 0))/18; env=challengers.get("environment_physics") or {}; weather_abs=abs(_num(env.get("flight_environment_index"),0)); venue=challengers.get("venue_park") or {}; park_dev=abs(_num(venue.get("factor"),1)-1)
    return [h+a,starter_uncertainty,.5*(stress("home")+stress("away")),lineup_missing,weather_abs,park_dev]


def _solve(a:list[list[float]],b:list[float])->list[float]:
    n=len(b); m=[a[i][:]+[b[i]] for i in range(n)]
    for c in range(n):
        p=max(range(c,n),key=lambda r:abs(m[r][c])); m[c],m[p]=m[p],m[c]; d=m[c][c]
        if abs(d)<1e-10: continue
        m[c]=[v/d for v in m[c]]
        for r in range(n):
            if r==c: continue
            f=m[r][c]; m[r]=[m[r][j]-f*m[c][j] for j in range(n+1)]
    return [m[i][-1] for i in range(n)]


def _fit(xs:list[list[float]],ys:list[float])->dict[str,Any]:
    means=[sum(r[j] for r in xs)/len(xs) for j in range(len(FEATURES))]; std=[max(1e-6,math.sqrt(sum((r[j]-means[j])**2 for r in xs)/max(1,len(xs)-1))) for j in range(len(FEATURES))]; z=[[1.0]+[(r[j]-means[j])/std[j] for j in range(len(FEATURES))] for r in xs]; d=len(z[0]); gram=[[0.0]*d for _ in range(d)]; rhs=[0.0]*d
    for r,y in zip(z,ys):
        for i in range(d):
            rhs[i]+=r[i]*y
            for j in range(d): gram[i][j]+=r[i]*r[j]
    for i in range(1,d): gram[i][i]+=20.0
    beta=_solve(gram,rhs); return {"intercept":beta[0],"coefficients":dict(zip(FEATURES,beta[1:])),"means":dict(zip(FEATURES,means)),"std":dict(zip(FEATURES,std))}


def _mean_ci(values:list[float])->dict[str,Any]:
    if not values: return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None}
    mean=sum(values)/len(values)
    if len(values)<2: return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None}
    var=sum((x-mean)**2 for x in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-1.96*se,"ci95_upper":mean+1.96*se}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); usable=[r for r in settled if vector(r) is not None]; base={"schema":"pulsar-v14-heteroskedastic-distribution-challenger-v2","role":"CHALLENGER_ONLY","auto_activation":False,"promotion_eligible":False,"games":len(usable),"minimum_games":MIN_GAMES,"features":list(FEATURES),"downstream_validation_required":True}
    if len(usable)<MIN_GAMES: return {**base,"status":"COLLECTING"}
    xs=[]; ys=[]
    for row in usable:
        x=vector(row); hs=float(row["home_score"]); aws=float(row["away_score"]); hm=_num(row.get("home_mu"),4.4); am=_num(row.get("away_mu"),4.4); squared=((hs-hm)**2+(aws-am)**2)/2; baseline=max(1.0,(hm+am)/2); xs.append(x); ys.append(max(-.7,min(.7,math.log(max(.2,squared/baseline)))))
    split=int(len(xs)*.8); train_x,hold_x=xs[:split],xs[split:]; train_y,hold_y=ys[:split],ys[split:]
    if len(hold_x)<MIN_HOLDOUT: return {**base,"status":"COLLECTING","reason":"holdout_too_small"}
    model=_fit(train_x,train_y)
    def pred(x): return max(-.7,min(.7,float(model["intercept"])+sum(float(model["coefficients"][n])*(x[i]-float(model["means"][n]))/float(model["std"][n]) for i,n in enumerate(FEATURES))))
    gains=[y*y-(pred(x)-y)**2 for x,y in zip(hold_x,hold_y)]; evidence=_mean_ci(gains); learned=bool(evidence.get("ci95_lower") is not None and float(evidence["ci95_lower"])>0)
    return {**base,"status":"READY_DOWNSTREAM_EVAL" if learned else "REJECTED_OOS_VARIANCE_TARGET","variance_target_passes":learned,"model":model,"train_n":len(train_x),"holdout_n":len(hold_x),"paired_holdout_mse_gain":evidence,"variance_multiplier_contract":"exp(clipped predicted log multiplier), bounded later by score model","promotion_gate":"never directly promotable; must be integrated into distribution challenger and then pass paired final-score NLL + market proper-score gates","note":"Explaining variance is not sufficient evidence that betting probabilities improve."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    out=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); print(write(args.predictions,args.output).get("status"))
