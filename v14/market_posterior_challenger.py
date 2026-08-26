from __future__ import annotations

"""Market-informed probability posterior challenger with strict paired OOS gates.

Pure Pulsar baseball probabilities remain the independent primary product. A
log-odds blend with verified sharp consensus is downstream only and never
auto-activates. Promotion review requires paired holdout superiority versus both
Pulsar and sharp. Integer-total pushes are excluded.
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
MIN_HOLDOUT=100
ALPHAS=tuple(i/20 for i in range(21))
EPS=1e-9
MARKETS={"ML":"home_ml","RL_HOME_-1.5":"home_minus_1_5","RL_AWAY_-1.5":"away_minus_1_5","TOTAL_OVER":"over"}


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
def blend(model_p:float,sharp_p:float,alpha:float)->float: return _sigmoid(float(alpha)*_logit(model_p)+(1-float(alpha))*_logit(sharp_p))


def _outcome(row:dict[str,Any],market:str)->int|None:
    hs,aws=int(row["home_score"]),int(row["away_score"])
    if market=="ML": return int(hs>aws)
    if market=="RL_HOME_-1.5": return int(hs-aws>=2)
    if market=="RL_AWAY_-1.5": return int(aws-hs>=2)
    line=_num(row.get("total_line"))
    if line is None or abs((hs+aws)-line)<1e-9: return None
    return int(hs+aws>line)


def _observations(rows:list[dict[str,Any]],market:str)->list[tuple[float,float,int]]:
    key=MARKETS[market]; obs=[]
    for row in rows:
        model=_num((row.get("probabilities") or {}).get(key)); sharp=_num((((row.get("sharp_market") or {}).get("selections") or {}).get(key) or {}).get("fair_probability")); y=_outcome(row,market)
        if model is None or sharp is None or y is None or not (0<model<1 and 0<sharp<1): continue
        obs.append((model,sharp,int(y)))
    return obs


def _score(obs:list[tuple[float,float,int]],alpha:float)->dict[str,Any]:
    if not obs:return {"n":0,"brier":None,"log_loss":None}
    eps=1e-12; probs=[(blend(m,s,alpha),y) for m,s,y in obs]; return {"n":len(probs),"brier":sum((p-y)**2 for p,y in probs)/len(probs),"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in probs)/len(probs)}


def _mean_ci(values:list[float])->dict[str,Any]:
    if not values:return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None}
    mean=sum(values)/len(values)
    if len(values)<2:return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None}
    var=sum((x-mean)**2 for x in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-1.96*se,"ci95_upper":mean+1.96*se}


def _paired(obs:list[tuple[float,float,int]],alpha:float,reference_alpha:float)->dict[str,Any]:
    eps=1e-12; bd=[]; ld=[]
    for m,s,y in obs:
        cp=blend(m,s,alpha); rp=blend(m,s,reference_alpha); bd.append((rp-y)**2-(cp-y)**2); rl=-(y*math.log(max(eps,min(1-eps,rp)))+(1-y)*math.log(max(eps,min(1-eps,1-rp)))); cl=-(y*math.log(max(eps,min(1-eps,cp)))+(1-y)*math.log(max(eps,min(1-eps,1-cp)))); ld.append(rl-cl)
    return {"brier_gain":_mean_ci(bd),"logloss_gain":_mean_ci(ld)}


def _pass_vs_reference(evidence:dict[str,Any])->bool:
    b=evidence["brier_gain"]; l=evidence["logloss_gain"]; return bool(int(b.get("n") or 0)>=MIN_HOLDOUT and b.get("ci95_lower") is not None and float(b["ci95_lower"])>0 and l.get("ci95_lower") is not None and float(l["ci95_lower"])>=-.001)


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); markets={}
    for market in MARKETS:
        obs=_observations(settled,market); n=len(obs); base={"n":n,"minimum_n":MIN_MARKET_N,"active":False,"auto_activation":False,"pushes_excluded":market=="TOTAL_OVER"}
        if n<MIN_MARKET_N: markets[market]={**base,"status":"COLLECTING","reason":"insufficient_verified_sharp_observations"}; continue
        split=int(n*.80); train,holdout=obs[:split],obs[split:]
        if len(holdout)<MIN_HOLDOUT: markets[market]={**base,"status":"COLLECTING","reason":"holdout_too_small"}; continue
        candidates=[(_score(train,a)["log_loss"],_score(train,a)["brier"],a) for a in ALPHAS]; _,_,alpha=min(candidates,key=lambda x:(x[0],x[1])); posterior=_score(holdout,alpha); pulsar=_score(holdout,1.0); sharp=_score(holdout,0.0); vs_pulsar=_paired(holdout,alpha,1.0); vs_sharp=_paired(holdout,alpha,0.0); passes=_pass_vs_reference(vs_pulsar) and _pass_vs_reference(vs_sharp) and 0<alpha<1
        markets[market]={**base,"train_n":len(train),"holdout_n":len(holdout),"status":"PROMOTION_REVIEW" if passes else "REJECTED_OOS","passes":passes,"alpha_pulsar":alpha,"alpha_sharp":1-alpha,"holdout":{"posterior":posterior,"pulsar":pulsar,"sharp":sharp},"paired_gain_vs_pulsar":vs_pulsar,"paired_gain_vs_sharp":vs_sharp,"promotion_gate":"interior blend; paired Brier gain CI95 lower >0 and LogLoss lower >= -0.001 versus both Pulsar and sharp"}
    return {"schema":"pulsar-v14-market-posterior-challenger-v2","role":"CHALLENGER_ONLY","auto_activation":False,"baseball_probability_remains_independent":True,"chronological_holdout":True,"markets":markets,"note":"Market information is downstream only. Promotion requires explicit market-by-market OOS approval."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact

def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write(args.predictions,args.output); statuses={k:v.get("status") for k,v in artifact["markets"].items()}; print(f"PULSAR_V14_MARKET_POSTERIOR {statuses}")
if __name__=="__main__": main()
