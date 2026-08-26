from __future__ import annotations

"""Learned run-residual challenger for Pulsar V14.

This module is the replacement path for hand-tuned structural/context weights.
It learns only from strictly pregame features that were persisted at prediction
time, uses chronological train/holdout validation, and can never self-activate.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .distribution import probability_surface
from .model import RunProjection
from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS = Path("data/v14_predictions.jsonl")
ARTIFACT = Path("data/v14_residual_challenger.json")
MIN_GAMES = 600
RIDGE = 12.0
MAX_RUN_DELTA = 0.55

FEATURE_NAMES = (
    "starter_era", "starter_whip", "starter_k9", "starter_bb9", "starter_hr9", "starter_sample_weight",
    "lineup_ops", "lineup_coverage", "bullpen_taxed_rate", "bullpen_unavailable_rate", "bullpen_mean_pitches3",
    "rest_days", "travel_1000km", "timezone_shift", "previous_extra_innings", "temperature_centered", "wind_mph",
)


def _num(v: Any, default: float | None = None) -> float | None:
    try: out=float(v)
    except Exception: return default
    return out if math.isfinite(out) else default


def _side_features(row: dict[str, Any], side: str) -> list[float] | None:
    tf=row.get("training_features") or {}
    if tf.get("point_in_time") is not True: return None
    starter=tf.get(f"{side}_starter") or {}; lineup=tf.get(f"{side}_lineup") or {}; bullpen=((tf.get("bullpen") or {}).get(side) or {}); operational=((tf.get("operational") or {}).get(side) or {}); env=tf.get("environment") or {}
    relievers=[r for r in bullpen.get("relievers") or [] if isinstance(r,dict)]; n=max(1,len(relievers)); taxed=sum(bool(r.get("taxed")) for r in relievers)/n if relievers else 0.0; unavailable=sum(r.get("likely_unavailable") is True or r.get("available") is False for r in relievers)/n if relievers else 0.0; p3=[_num(r.get("pitches_last_3d")) for r in relievers]; p3=[x for x in p3 if x is not None]
    lineup_ops=_num(lineup.get("weighted_ops"),.725) or .725; coverage=_num(lineup.get("coverage"),0.0) or 0.0
    return [_num(starter.get("era"),4.35) or 4.35,_num(starter.get("whip"),1.32) or 1.32,_num(starter.get("k9"),8.5) or 8.5,_num(starter.get("bb9"),3.2) or 3.2,_num(starter.get("hr9"),1.15) or 1.15,_num(starter.get("sample_weight"),0.0) or 0.0,lineup_ops,coverage,taxed,unavailable,(sum(p3)/len(p3) if p3 else 0.0),_num(operational.get("rest_days"),0.0) or 0.0,(_num(operational.get("travel_km"),0.0) or 0.0)/1000.0,abs(_num(operational.get("timezone_shift_hours_approx"),0.0) or 0.0),1.0 if operational.get("previous_extra_innings") else 0.0,((_num(env.get("temperature_f"),70.0) or 70.0)-70.0)/20.0,(_num(env.get("wind_mph"),0.0) or 0.0)/15.0]


def _standardize(xs: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    d=len(xs[0]); means=[sum(r[j] for r in xs)/len(xs) for j in range(d)]; std=[]
    for j in range(d):
        var=sum((r[j]-means[j])**2 for r in xs)/max(1,len(xs)-1); std.append(max(1e-6,math.sqrt(var)))
    return [[(r[j]-means[j])/std[j] for j in range(d)] for r in xs],means,std


def _apply_standardize(x:list[float],means:list[float],std:list[float])->list[float]: return [(x[j]-means[j])/std[j] for j in range(len(x))]


def _solve(a:list[list[float]],b:list[float])->list[float]:
    n=len(b); m=[a[i][:]+[b[i]] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(m[r][col])); m[col],m[pivot]=m[pivot],m[col]; div=m[col][col]
        if abs(div)<1e-10: continue
        m[col]=[v/div for v in m[col]]
        for r in range(n):
            if r==col: continue
            factor=m[r][col]
            if factor: m[r]=[m[r][c]-factor*m[col][c] for c in range(n+1)]
    return [m[i][-1] for i in range(n)]


def _fit(xs:list[list[float]],ys:list[float])->dict[str,Any]:
    zx,means,std=_standardize(xs); z=[[1.0]+r for r in zx]; d=len(z[0]); gram=[[0.0]*d for _ in range(d)]; rhs=[0.0]*d
    for row,y in zip(z,ys):
        for i in range(d):
            rhs[i]+=row[i]*y
            for j in range(d): gram[i][j]+=row[i]*row[j]
    for i in range(1,d): gram[i][i]+=RIDGE
    beta=_solve(gram,rhs); return {"intercept":beta[0],"coefficients":dict(zip(FEATURE_NAMES,beta[1:])),"means":dict(zip(FEATURE_NAMES,means)),"std":dict(zip(FEATURE_NAMES,std))}


def _predict(model:dict[str,Any],x:list[float])->float:
    means=[model["means"][n] for n in FEATURE_NAMES]; std=[model["std"][n] for n in FEATURE_NAMES]; z=_apply_standardize(x,means,std); value=float(model["intercept"])+sum(float(model["coefficients"][n])*z[i] for i,n in enumerate(FEATURE_NAMES)); return max(-MAX_RUN_DELTA,min(MAX_RUN_DELTA,value))


def _metrics(rows:list[dict[str,Any]],home_model:dict[str,Any]|None,away_model:dict[str,Any]|None)->dict[str,Any]:
    run_err=[]; total_err=[]; brier=[]; logloss=[]; eps=1e-12; used=0
    for row in rows:
        hf=_side_features(row,"home"); af=_side_features(row,"away"); hmu=_num(row.get("home_mu")); amu=_num(row.get("away_mu")); line=_num(row.get("total_line"))
        if hf is None or af is None or None in {hmu,amu,line}: continue
        dh=_predict(home_model,hf) if home_model else 0.0; da=_predict(away_model,af) if away_model else 0.0; hm=max(.2,hmu+dh); am=max(.2,amu+da); hs=int(row["home_score"]); aws=int(row["away_score"]); run_err.extend((abs(hm-hs),abs(am-aws))); total_err.append(abs(hm+am-hs-aws)); used+=1
        proj=RunProjection(game_pk=str(row.get("game_pk") or "x"),game_date=str(row.get("game_date") or ""),analyzed_at=str(row.get("analyzed_at") or ""),home=str(row.get("home") or "H"),away=str(row.get("away") or "A"),home_mu=hm,away_mu=am,total_line=line); surf,_=probability_surface(proj); vals=((surf.home_ml,int(hs>aws)),(surf.home_minus_1_5,int(hs-aws>=2)),(surf.away_minus_1_5,int(aws-hs>=2)),(surf.over,int(hs+aws>line)))
        for p,y in vals: brier.append((p-y)**2); logloss.append(-(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p)))))
    return {"games":used,"team_run_mae":sum(run_err)/len(run_err) if run_err else None,"total_run_mae":sum(total_err)/len(total_err) if total_err else None,"brier":sum(brier)/len(brier) if brier else None,"log_loss":sum(logloss)/len(logloss) if logloss else None}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); usable=[r for r in settled if _side_features(r,"home") is not None and _side_features(r,"away") is not None]; n=len(usable); base={"schema":"pulsar-v14-run-residual-challenger-v1","role":"CHALLENGER_ONLY","auto_activation":False,"games":n,"minimum_games":MIN_GAMES,"feature_names":list(FEATURE_NAMES)}
    if n<MIN_GAMES: return {**base,"status":"COLLECTING","reason":"insufficient_pit_feature_rows"}
    split=int(n*.80); train,holdout=usable[:split],usable[split:]; hx=[];hy=[];ax=[];ay=[]
    for row in train:
        hf=_side_features(row,"home"); af=_side_features(row,"away"); hmu=_num(row.get("home_mu")); amu=_num(row.get("away_mu"))
        if hf is None or af is None or hmu is None or amu is None: continue
        hx.append(hf); ax.append(af); hy.append(float(row["home_score"])-hmu); ay.append(float(row["away_score"])-amu)
    home_model=_fit(hx,hy); away_model=_fit(ax,ay); champion=_metrics(holdout,None,None); candidate=_metrics(holdout,home_model,away_model); run_gain=float(champion["team_run_mae"])-float(candidate["team_run_mae"]); total_gain=float(champion["total_run_mae"])-float(candidate["total_run_mae"]); brier_gain=float(champion["brier"])-float(candidate["brier"]); logloss_gain=float(champion["log_loss"])-float(candidate["log_loss"]); passes=run_gain>=.01 and total_gain>=0 and brier_gain>0 and logloss_gain>=0
    return {**base,"status":"PROMOTION_ELIGIBLE" if passes else "REJECTED_OOS","passes":passes,"home_model":home_model,"away_model":away_model,"champion_holdout":champion,"candidate_holdout":candidate,"team_run_mae_gain":run_gain,"total_run_mae_gain":total_gain,"brier_gain":brier_gain,"logloss_gain":logloss_gain,"note":"Never loaded by production automatically. Promotion requires explicit paired-OOS review and a versioned champion change."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write(args.predictions,args.output); print(f"PULSAR_V14_RESIDUAL_CHALLENGER status={artifact.get('status')} games={artifact.get('games')}")

if __name__=="__main__": main()
