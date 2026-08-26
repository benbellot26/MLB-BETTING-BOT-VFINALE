from __future__ import annotations

"""Chronological score-distribution challenger with paired OOS promotion gates."""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .champion_contract import validated_extra_innings_home_probability
from .distribution import extra_innings_terminal_kernel, joint_score_matrix, probability_surface
from .model import RunProjection
from .tracking import _read_jsonl, _canonical_settled

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_distribution_candidate.json")
DISPERSION_GRID=(4.0,4.5,5.5,6.5,7.5,9.0,11.0,14.0)
SIGMA_GRID=(0.00,0.04,0.08,0.12,0.16,0.20)
MIN_GAMES=600
MIN_HOLDOUT=100
MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _final_score_probability(hs:int,aws:int,joint:list[list[float]],kernel:list[tuple[int,int,float]])->float:
    p=0.0
    if hs!=aws and hs<len(joint) and aws<len(joint[0]): p+=joint[hs][aws]
    limit=min(len(joint),len(joint[0]))
    for r in range(limit):
        tie=joint[r][r]
        if tie<=0: continue
        for hadd,aadd,kp in kernel:
            if r+hadd==hs and r+aadd==aws: p+=tie*kp
    return max(1e-15,p)


def _outcomes(hs:int,aws:int,line:float)->dict[str,int|None]:
    total=hs+aws
    return {"ML":int(hs>aws),"RL_HOME_-1.5":int(hs-aws>=2),"RL_AWAY_-1.5":int(aws-hs>=2),"TOTAL_OVER":None if abs(total-line)<1e-9 else int(total>line)}


def _evaluate(rows:list[dict[str,Any]],dispersion:float,sigma:float)->dict[str,Any]:
    eps=1e-12; extra,_=validated_extra_innings_home_probability(); score_by_game={}; markets_by_game={m:{} for m in MARKETS}
    for row in rows:
        hmu,amu,line=_num(row.get("home_mu")),_num(row.get("away_mu")),_num(row.get("total_line"))
        if None in {hmu,amu,line}: continue
        hs=int(row["home_score"]); aws=int(row["away_score"]); gid=str(row.get("game_pk") or "")
        projection=RunProjection(game_pk=gid or "x",game_date=str(row.get("game_date") or ""),analyzed_at=str(row.get("analyzed_at") or ""),home=str(row.get("home") or "H"),away=str(row.get("away") or "A"),home_mu=float(hmu),away_mu=float(amu),total_line=float(line),dispersion=dispersion,environment_sigma=sigma,extra_innings_home_probability=extra)
        joint,_=joint_score_matrix(float(hmu),float(amu),dispersion=dispersion,environment_sigma=sigma); kernel=extra_innings_terminal_kernel(float(hmu),float(amu),extra); score_by_game[gid]=-math.log(_final_score_probability(hs,aws,joint,kernel)); surf,_=probability_surface(projection); outcomes=_outcomes(hs,aws,float(line)); probs={"ML":surf.home_ml,"RL_HOME_-1.5":surf.home_minus_1_5,"RL_AWAY_-1.5":surf.away_minus_1_5,"TOTAL_OVER":surf.over}
        for market in MARKETS:
            y=outcomes[market]
            if y is not None: markets_by_game[market][gid]=(float(probs[market]),int(y))
    def metrics(items:list[tuple[float,int]])->dict[str,Any]:
        if not items: return {"n":0,"brier":None,"log_loss":None}
        return {"n":len(items),"brier":sum((p-y)**2 for p,y in items)/len(items),"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items)}
    market_metrics={m:metrics(list(markets_by_game[m].values())) for m in MARKETS}; all_items=[item for m in MARKETS for item in markets_by_game[m].values()]
    return {"score_nll":sum(score_by_game.values())/len(score_by_game) if score_by_game else None,"score_games":len(score_by_game),"overall":metrics(all_items),"markets":market_metrics,"_score_by_game":score_by_game,"_markets_by_game":markets_by_game}


def _mean_ci(values:list[float])->dict[str,Any]:
    if not values: return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None}
    mean=sum(values)/len(values)
    if len(values)<2: return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None}
    var=sum((x-mean)**2 for x in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-1.96*se,"ci95_upper":mean+1.96*se}


def _paired(candidate:dict[str,Any],champion:dict[str,Any])->dict[str,Any]:
    common=sorted(set(candidate["_score_by_game"]) & set(champion["_score_by_game"])); score_ci=_mean_ci([champion["_score_by_game"][g]-candidate["_score_by_game"][g] for g in common]); markets={}; eps=1e-12
    for market in MARKETS:
        crows=candidate["_markets_by_game"][market]; hrows=champion["_markets_by_game"][market]; games=sorted(set(crows)&set(hrows)); bd=[]; ld=[]
        for g in games:
            cp,y=crows[g]; hp,hy=hrows[g]
            if y!=hy: continue
            bd.append((hp-y)**2-(cp-y)**2); cl=-(y*math.log(max(eps,min(1-eps,cp)))+(1-y)*math.log(max(eps,min(1-eps,1-cp)))); hl=-(y*math.log(max(eps,min(1-eps,hp)))+(1-y)*math.log(max(eps,min(1-eps,1-hp)))); ld.append(hl-cl)
        markets[market]={"brier_gain":_mean_ci(bd),"logloss_gain":_mean_ci(ld),"pushes_excluded":market=="TOTAL_OVER"}
    return {"score_nll_gain":score_ci,"markets":markets}


def _public(score:dict[str,Any])->dict[str,Any]: return {k:v for k,v in score.items() if not k.startswith("_")}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); n=len(settled); base={"schema":"pulsar-v14-distribution-challenger-v3","role":"CHALLENGER_ONLY","auto_activation":False,"games":n,"minimum_games":MIN_GAMES,"primary_objective":"final_score_negative_log_likelihood","paired_holdout_inference":True}
    if n<MIN_GAMES: return {**base,"status":"COLLECTING","reason":"insufficient_games"}
    split=max(400,int(n*.80)); train,holdout=settled[:split],settled[split:]
    if len(holdout)<MIN_HOLDOUT: return {**base,"status":"COLLECTING","reason":"holdout_too_small"}
    scored=[]
    for d in DISPERSION_GRID:
        for s in SIGMA_GRID:
            score=_evaluate(train,d,s)
            if score["score_nll"] is not None: scored.append((float(score["score_nll"]),d,s,score))
    if not scored: return {**base,"status":"COLLECTING","reason":"no_score_likelihood_rows"}
    _,d,s,train_score=min(scored,key=lambda x:x[0]); candidate=_evaluate(holdout,d,s); champion=_evaluate(holdout,7.5,.08); paired=_paired(candidate,champion); score_ci=paired["score_nll_gain"]
    market_nonreg=True
    for market,row in paired["markets"].items():
        b=row["brier_gain"]; l=row["logloss_gain"]
        if int(b.get("n") or 0)<MIN_HOLDOUT or b.get("ci95_lower") is None or float(b["ci95_lower"])<-.0015: market_nonreg=False
        if int(l.get("n") or 0)<MIN_HOLDOUT or l.get("ci95_lower") is None or float(l["ci95_lower"])<-.003: market_nonreg=False
    passes=bool(int(score_ci.get("n") or 0)>=MIN_HOLDOUT and score_ci.get("ci95_lower") is not None and float(score_ci["ci95_lower"])>0 and market_nonreg)
    return {**base,"status":"PROMOTION_ELIGIBLE" if passes else "REJECTED_OOS","passes":passes,"candidate":{"dispersion":d,"environment_sigma":s,"train":_public(train_score),"holdout":_public(candidate)},"champion_holdout":_public(champion),"paired_holdout":paired,"per_market_nonregression":market_nonreg,"promotion_gate":"paired score-NLL gain CI95 lower >0; each market paired Brier CI95 >= -0.0015 and LogLoss CI95 >= -0.003","note":"Artifact never changes runtime automatically; promotion requires deliberate versioned champion change."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write(args.predictions,args.output); print(f"PULSAR_V14_DISTRIBUTION_CHALLENGER status={artifact.get('status')} games={artifact.get('games')}")

if __name__=="__main__": main()
