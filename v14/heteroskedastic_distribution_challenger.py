from __future__ import annotations

"""Conditional-variance research layer for V14 score distributions.

Games with identical expected total runs need not have identical variance. This
module learns a bounded variance multiplier from strictly-pregame uncertainty
features. It never changes champion dispersion automatically.
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
FEATURES=("projected_total","starter_uncertainty","bullpen_stress","lineup_missing","weather_abs","park_deviation")


def _num(v:Any,d:float=0.0)->float:
    try: out=float(v)
    except Exception: return d
    return out if math.isfinite(out) else d


def vector(row:dict[str,Any])->list[float]|None:
    tf=row.get("training_features") or {}
    if tf.get("point_in_time") is not True: return None
    h=_num(row.get("home_mu"),4.4); a=_num(row.get("away_mu"),4.4); q=tf.get("data_quality") or {}; challengers=tf.get("research_challengers") or {}; hu=(challengers.get("home_starter_usage") or {}); au=(challengers.get("away_starter_usage") or {}); bullpen=tf.get("bullpen") or {}
    def stress(side:str)->float:
        rel=[x for x in ((bullpen.get(side) or {}).get("relievers") or []) if isinstance(x,dict)]
        return sum(bool(x.get("taxed")) or bool(x.get("likely_unavailable")) for x in rel)/len(rel) if rel else 0.0
    starter_uncertainty=1-.5*(_num(hu.get("confidence"),0)+_num(au.get("confidence"),0)); lineup_missing=(18-int(q.get("home_lineup_count") or 0)-int(q.get("away_lineup_count") or 0))/18; env=(challengers.get("environment_physics") or {}); weather_abs=abs(_num(env.get("flight_environment_index"),0)); venue=(challengers.get("venue_park") or {}); park_dev=abs(_num(venue.get("factor"),1)-1)
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


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); usable=[r for r in settled if vector(r) is not None]; base={"schema":"pulsar-v14-heteroskedastic-distribution-challenger-v1","role":"CHALLENGER_ONLY","auto_activation":False,"games":len(usable),"minimum_games":MIN_GAMES,"features":list(FEATURES)}
    if len(usable)<MIN_GAMES: return {**base,"status":"COLLECTING"}
    xs=[]; ys=[]
    for row in usable:
        x=vector(row); hs=float(row["home_score"]); aws=float(row["away_score"]); hm=_num(row.get("home_mu"),4.4); am=_num(row.get("away_mu"),4.4); squared=((hs-hm)**2+(aws-am)**2)/2; baseline=max(1.0,(hm+am)/2); xs.append(x); ys.append(max(-.7,min(.7,math.log(max(.2,squared/baseline)))))
    split=int(len(xs)*.8); model=_fit(xs[:split],ys[:split]); hold=xs[split:]; targets=ys[split:]
    def pred(x): return max(-.7,min(.7,float(model["intercept"])+sum(float(model["coefficients"][n])*(x[i]-float(model["means"][n]))/float(model["std"][n]) for i,n in enumerate(FEATURES))))
    base_mse=sum(y*y for y in targets)/len(targets); cand_mse=sum((pred(x)-y)**2 for x,y in zip(hold,targets))/len(targets); gain=base_mse-cand_mse
    return {**base,"status":"PROMOTION_REVIEW" if gain>0 else "REJECTED_OOS","passes":gain>0,"model":model,"holdout_log_variance_mse_gain":gain,"variance_multiplier_contract":"exp(clipped predicted log multiplier), bounded later by score model","note":"Must still improve score NLL and downstream market proper scores before promotion."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    out=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); print(write(args.predictions,args.output).get("status"))
