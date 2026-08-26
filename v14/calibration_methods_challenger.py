from __future__ import annotations

"""Research comparison of Identity, Platt and Beta calibration.

This artifact never auto-activates. Production calibration remains governed by
`probability_calibration.py`; a method may only be promoted after chronological
OOS evidence.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .probability_calibration import CANONICAL_MARKETS, _items, _latest_settled_by_game, _read_jsonl, _scores, _sigmoid, _logit, _fit_platt

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_calibration_methods_candidate.json")
MIN_GAMES=500
EPS=1e-9


def _solve3(a:list[list[float]],b:list[float])->list[float]:
    m=[a[i][:]+[b[i]] for i in range(3)]
    for col in range(3):
        pivot=max(range(col,3),key=lambda r:abs(m[r][col])); m[col],m[pivot]=m[pivot],m[col]
        div=m[col][col]
        if abs(div)<1e-10: continue
        m[col]=[v/div for v in m[col]]
        for r in range(3):
            if r==col: continue
            f=m[r][col]; m[r]=[m[r][c]-f*m[col][c] for c in range(4)]
    return [m[i][3] for i in range(3)]


def _beta_features(p:float)->tuple[float,float,float]:
    q=min(1-EPS,max(EPS,float(p))); return math.log(q),math.log(1-q),1.0


def _fit_beta(items:list[tuple[float,int]])->list[float]:
    beta=[1.0,-1.0,0.0]
    for _ in range(60):
        h=[[0.0]*3 for _ in range(3)]; g=[0.0]*3
        for p,y in items:
            x=_beta_features(p); q=_sigmoid(sum(beta[i]*x[i] for i in range(3))); w=max(1e-8,q*(1-q)); err=q-y
            for i in range(3):
                g[i]+=err*x[i]
                for j in range(3): h[i][j]+=w*x[i]*x[j]
        for i,target in ((0,1.0),(1,-1.0),(2,0.0)): h[i][i]+=2.0; g[i]+=2.0*(beta[i]-target)
        step=_solve3(h,g); scale=max(1.0,max(abs(x)/.25 for x in step)); beta=[beta[i]-step[i]/scale for i in range(3)]
        if max(abs(x/scale) for x in step)<1e-7: break
    return beta


def _apply_beta(p:float,beta:list[float])->float:
    x=_beta_features(p); return _sigmoid(sum(beta[i]*x[i] for i in range(3)))


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    canonical=_latest_settled_by_game(rows); result={"schema":"pulsar-v14-calibration-methods-challenger-v1","role":"CHALLENGER_ONLY","auto_activation":False,"markets":{}}
    for market in CANONICAL_MARKETS:
        items=_items(canonical,market); n=len(items); base={"n":n,"minimum_n":MIN_GAMES}
        if n<MIN_GAMES: result["markets"][market]={**base,"status":"COLLECTING"}; continue
        split=int(n*.8); train,holdout=items[:split],items[split:]; a,b=_fit_platt(train); beta=_fit_beta(train); candidates={"IDENTITY":holdout,"PLATT":[(_sigmoid(a*_logit(p)+b),y) for p,y in holdout],"BETA":[(_apply_beta(p,beta),y) for p,y in holdout]}; metrics={name:_scores(vals) for name,vals in candidates.items()}; winner=min(metrics,key=lambda name:(float(metrics[name]["brier"]),float(metrics[name]["log_loss"])))
        result["markets"][market]={**base,"status":"PROMOTION_REVIEW" if winner!="IDENTITY" else "VALIDATED_IDENTITY_CANDIDATE","winner":winner,"metrics":metrics,"platt":{"slope":a,"intercept":b},"beta":{"a":beta[0],"b":beta[1],"c":beta[2]},"note":"Winner is OOS evidence only; no automatic production change."}
    return result


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    out=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); out=write(args.predictions,args.output); print(f"PULSAR_V14_CAL_METHODS markets={len(out['markets'])}")

if __name__=="__main__": main()
