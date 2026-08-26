from __future__ import annotations

"""Chronological score-distribution challenger.

Primary fitting objective is final-score negative log likelihood, not an average
of four correlated betting markets.  Market Brier/LogLoss remain downstream
non-regression gates.
"""

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


def _num(v:Any)->float|None:
    try: out=float(v)
    except Exception: return None
    return out if math.isfinite(out) else None


def _final_score_probability(hs:int,aws:int,joint:list[list[float]],kernel:list[tuple[int,int,float]])->float:
    p=0.0
    # A non-tied regulation score can directly be the final score.
    if hs!=aws and hs<len(joint) and aws<len(joint[0]): p+=joint[hs][aws]
    # Extra-inning finals originate from any regulation tie compatible with the
    # terminal added-run kernel.
    limit=min(len(joint),len(joint[0]))
    for r in range(limit):
        tie=joint[r][r]
        if tie<=0: continue
        for hadd,aadd,kp in kernel:
            if r+hadd==hs and r+aadd==aws: p+=tie*kp
    return max(1e-15,p)


def _score(rows:list[dict[str,Any]],dispersion:float,sigma:float)->dict[str,Any]:
    eps=1e-12; market_values={k:[] for k in ("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")}; score_nll=[]; extra,_=validated_extra_innings_home_probability()
    for row in rows:
        hmu,amu,line=_num(row.get("home_mu")),_num(row.get("away_mu")),_num(row.get("total_line"))
        if None in {hmu,amu,line}: continue
        hs=int(row["home_score"]); aws=int(row["away_score"]); projection=RunProjection(game_pk=str(row.get("game_pk") or "x"),game_date=str(row.get("game_date") or ""),analyzed_at=str(row.get("analyzed_at") or ""),home=str(row.get("home") or "H"),away=str(row.get("away") or "A"),home_mu=float(hmu),away_mu=float(amu),total_line=float(line),dispersion=dispersion,environment_sigma=sigma,extra_innings_home_probability=extra)
        joint,_tail=joint_score_matrix(float(hmu),float(amu),dispersion=dispersion,environment_sigma=sigma); kernel=extra_innings_terminal_kernel(float(hmu),float(amu),extra); score_nll.append(-math.log(_final_score_probability(hs,aws,joint,kernel)))
        surf,_=probability_surface(projection)
        for name,p,y in (("ML",surf.home_ml,int(hs>aws)),("RL_HOME_-1.5",surf.home_minus_1_5,int(hs-aws>=2)),("RL_AWAY_-1.5",surf.away_minus_1_5,int(aws-hs>=2)),("TOTAL_OVER",surf.over,int(hs+aws>float(line)))): market_values[name].append((p,y))
    out={}; all_items=[]
    for name,items in market_values.items():
        all_items+=items
        out[name]={"n":len(items),"brier":sum((p-y)**2 for p,y in items)/len(items) if items else None,"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items) if items else None}
    return {"score_nll":sum(score_nll)/len(score_nll) if score_nll else None,"score_games":len(score_nll),"overall":{"n":len(all_items),"brier":sum((p-y)**2 for p,y in all_items)/len(all_items) if all_items else None,"log_loss":-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in all_items)/len(all_items) if all_items else None},"markets":out}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); n=len(settled); base={"schema":"pulsar-v14-distribution-challenger-v2","role":"CHALLENGER_ONLY","auto_activation":False,"games":n,"minimum_games":MIN_GAMES,"primary_objective":"final_score_negative_log_likelihood"}
    if n<MIN_GAMES: return {**base,"status":"COLLECTING","reason":"insufficient_games"}
    split=max(400,int(n*.80)); train,holdout=settled[:split],settled[split:]
    if len(holdout)<100: return {**base,"status":"COLLECTING","reason":"holdout_too_small"}
    scored=[]
    for d in DISPERSION_GRID:
        for s in SIGMA_GRID:
            score=_score(train,d,s)
            if score["score_nll"] is not None: scored.append((float(score["score_nll"]),d,s,score))
    if not scored: return {**base,"status":"COLLECTING","reason":"no_score_likelihood_rows"}
    _,d,s,train_score=min(scored,key=lambda x:x[0]); candidate=_score(holdout,d,s); champion=_score(holdout,7.5,.08)
    score_gain=float(champion["score_nll"])-float(candidate["score_nll"]); brier_gain=float(champion["overall"]["brier"])-float(candidate["overall"]["brier"]); ll_gain=float(champion["overall"]["log_loss"])-float(candidate["overall"]["log_loss"])
    per_market_nonreg=all(float(candidate["markets"][m]["brier"])<=float(champion["markets"][m]["brier"])+.0015 for m in candidate["markets"] if candidate["markets"][m]["brier"] is not None)
    passes=score_gain>0 and brier_gain>=0 and ll_gain>=0 and per_market_nonreg
    return {**base,"status":"PROMOTION_ELIGIBLE" if passes else "REJECTED_OOS","passes":passes,"candidate":{"dispersion":d,"environment_sigma":s,"train":train_score,"holdout":candidate},"champion_holdout":champion,"score_nll_gain":score_gain,"brier_gain":brier_gain,"logloss_gain":ll_gain,"per_market_nonregression":per_market_nonreg,"note":"Artifact never changes runtime automatically; promotion requires deliberate versioned champion change."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write(args.predictions,args.output); print(f"PULSAR_V14_DISTRIBUTION_CHALLENGER status={artifact.get('status')} games={artifact.get('games')}")


if __name__=="__main__": main()
