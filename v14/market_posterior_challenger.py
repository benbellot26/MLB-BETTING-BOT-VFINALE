from __future__ import annotations

"""Market-informed probability posterior challenger.

Pure Pulsar baseball probabilities remain the auditable primary product. This
shadow challenger learns whether a log-odds blend with a verified sharp market
adds predictive value. It never feeds market information back into the baseball
model and can never auto-activate.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_market_posterior_candidate.json")
MIN_MARKET_N=600
ALPHAS=tuple(i/20 for i in range(21))
EPS=1e-9

MARKETS={
    "ML":("home_ml",lambda hs,aws,line:int(hs>aws)),
    "RL_HOME_-1.5":("home_minus_1_5",lambda hs,aws,line:int(hs-aws>=2)),
    "RL_AWAY_-1.5":("away_minus_1_5",lambda hs,aws,line:int(aws-hs>=2)),
    "TOTAL_OVER":("over",lambda hs,aws,line:int(line is not None and hs+aws>line)),
}


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception:return None
    return out if math.isfinite(out) else None


def _clip(p:float)->float:return min(1-EPS,max(EPS,float(p)))
def _logit(p:float)->float:
    q=_clip(p); return math.log(q/(1-q))
def _sigmoid(z:float)->float:
    if z>=0:
        e=math.exp(-z); return 1/(1+e)
    e=math.exp(z); return e/(1+e)


def blend(model_p:float,sharp_p:float,alpha:float)->float:
    """alpha=1 is Pulsar-only; alpha=0 is sharp-market-only."""
    return _sigmoid(float(alpha)*_logit(model_p)+(1-float(alpha))*_logit(sharp_p))


def _observations(rows:list[dict[str,Any]],market:str)->list[tuple[float,float,int]]:
    key,outcome=MARKETS[market]; obs=[]
    for row in rows:
        model=_num((row.get("probabilities") or {}).get(key)); sharp=_num((((row.get("sharp_market") or {}).get("selections") or {}).get(key) or {}).get("fair_probability")); line=_num(row.get("total_line"))
        if model is None or sharp is None or not (0<model<1 and 0<sharp<1):continue
        hs,aws=int(row["home_score"]),int(row["away_score"]); obs.append((model,sharp,outcome(hs,aws,line)))
    return obs


def _score(obs:list[tuple[float,float,int]],alpha:float)->dict[str,Any]:
    if not obs:return {"n":0,"brier":None,"log_loss":None}
    eps=1e-12; probs=[(blend(m,s,alpha),y) for m,s,y in obs]
    return {"n":len(probs),"brier":sum((p-y)**2 for p,y in probs)/len(probs),"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in probs)/len(probs)}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); markets={}
    for market in MARKETS:
        obs=_observations(settled,market); n=len(obs); base={"n":n,"minimum_n":MIN_MARKET_N,"active":False,"auto_activation":False}
        if n<MIN_MARKET_N:
            markets[market]={**base,"status":"COLLECTING","reason":"insufficient_verified_sharp_observations"}; continue
        split=int(n*.80); train,holdout=obs[:split],obs[split:]
        if len(holdout)<100:
            markets[market]={**base,"status":"COLLECTING","reason":"holdout_too_small"}; continue
        candidates=[(_score(train,a)["log_loss"],_score(train,a)["brier"],a) for a in ALPHAS]; _,_,alpha=min(candidates,key=lambda x:(x[0],x[1])); posterior=_score(holdout,alpha); pulsar=_score(holdout,1.0); sharp=_score(holdout,0.0); brier_vs_p=float(pulsar["brier"])-float(posterior["brier"]); ll_vs_p=float(pulsar["log_loss"])-float(posterior["log_loss"]); brier_vs_s=float(sharp["brier"])-float(posterior["brier"]); ll_vs_s=float(sharp["log_loss"])-float(posterior["log_loss"]); passes=brier_vs_p>0 and ll_vs_p>0 and brier_vs_s>=0 and ll_vs_s>=0
        markets[market]={**base,"status":"PROMOTION_ELIGIBLE" if passes else "REJECTED_OOS","passes":passes,"alpha_pulsar":alpha,"alpha_sharp":1-alpha,"holdout":{"posterior":posterior,"pulsar":pulsar,"sharp":sharp},"brier_gain_vs_pulsar":brier_vs_p,"logloss_gain_vs_pulsar":ll_vs_p,"brier_gain_vs_sharp":brier_vs_s,"logloss_gain_vs_sharp":ll_vs_s}
    return {"schema":"pulsar-v14-market-posterior-challenger-v1","role":"CHALLENGER_ONLY","auto_activation":False,"baseball_probability_remains_independent":True,"markets":markets,"note":"Market information is downstream only. Promotion requires explicit market-by-market OOS approval."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write(args.predictions,args.output); statuses={k:v.get("status") for k,v in artifact["markets"].items()}; print(f"PULSAR_V14_MARKET_POSTERIOR {statuses}")

if __name__=="__main__":main()
