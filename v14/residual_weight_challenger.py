from __future__ import annotations

"""Regularized learned-weight challenger for V14 advanced residual components.

The champion's advanced layer intentionally uses fixed conservative coefficients.
This challenger asks a narrower question: given the *persisted PIT component
run-deltas already produced by the champion*, would a strongly regularized set of
multipliers improve realized team-run MSE on a chronological holdout?

It does not fetch data, cannot auto-activate, and never uses market probabilities.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .snapshot_policy import select_canonical

PREDICTIONS=Path("data/v14_predictions.jsonl")
OUTPUT=Path("data/v14_residual_weight_candidate.json")
MIN_GAMES=300
RIDGE=40.0
FEATURES=("offense","prevention","fielding","timezone","physics")


def _num(value:Any)->float|None:
    try:x=float(value)
    except Exception:return None
    return x if math.isfinite(x) else None


def _read(path:Path|str)->list[dict[str,Any]]:
    p=Path(path)
    if not p.exists():return []
    rows=[]
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:row=json.loads(line)
        except Exception:continue
        if isinstance(row,dict):rows.append(row)
    return rows


def _policy(row:dict[str,Any])->str|None:
    value=row.get("probability_policy_id") or ((row.get("calibration") or {}).get("probability_policy_id"))
    return str(value) if value else None


def _solve(a:list[list[float]],b:list[float])->list[float]|None:
    n=len(b);m=[list(a[i])+[b[i]] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(m[r][col]))
        if abs(m[pivot][col])<1e-10:return None
        m[col],m[pivot]=m[pivot],m[col];div=m[col][col];m[col]=[x/div for x in m[col]]
        for r in range(n):
            if r==col:continue
            f=m[r][col]
            if f:m[r]=[m[r][c]-f*m[col][c] for c in range(n+1)]
    return [m[i][n] for i in range(n)]


def _fit(samples:list[tuple[list[float],float]],ridge:float=RIDGE)->list[float]|None:
    n=1+len(FEATURES);a=[[0.0]*n for _ in range(n)];b=[0.0]*n
    for features,target in samples:
        x=[1.0,*features]
        for i in range(n):
            b[i]+=x[i]*target
            for j in range(n):a[i][j]+=x[i]*x[j]
    # Prior is intercept=0 and multiplier=1 for each champion component. Strong
    # shrinkage makes the challenger ask for clear evidence before moving weights.
    prior=[0.0]+[1.0]*len(FEATURES)
    for i in range(1,n):a[i][i]+=ridge;b[i]+=ridge*prior[i]
    return _solve(a,b)


def _team_sample(row:dict[str,Any],side:str)->tuple[list[float],float,float,float]|None:
    tf=row.get("training_features") or {};base=tf.get("base_run_projection") or {};ctx=tf.get("context_adjustment") or {};adv=tf.get("advanced_stats_adjustment") or {};components=adv.get("components") or {}
    base_mu=_num(base.get(f"{side}_mu"));ctx_delta=_num(ctx.get(f"{side}_delta"));score=_num(row.get(f"{side}_score"));final_mu=_num(row.get(f"{side}_mu"))
    if None in (base_mu,ctx_delta,score,final_mu):return None
    pre=float(base_mu)*(1.0+float(ctx_delta))
    if side=="home":
        offense=(components.get("home_offense_statcast_matchup_baserunning") or {}).get("delta")
        prevention=(components.get("away_pitching_statcast_depth") or {}).get("delta_for_opponent_scoring")
        fielding=(components.get("away_defense_catcher") or {}).get("delta_for_opponent_scoring")
        timezone=(components.get("home_exact_timezone_residual") or {}).get("delta")
    else:
        offense=(components.get("away_offense_statcast_matchup_baserunning") or {}).get("delta")
        prevention=(components.get("home_pitching_statcast_depth") or {}).get("delta_for_opponent_scoring")
        fielding=(components.get("home_defense_catcher") or {}).get("delta_for_opponent_scoring")
        timezone=(components.get("away_exact_timezone_residual") or {}).get("delta")
    physics=(components.get("venue_relative_environment_physics") or {}).get("delta")
    vals=[_num(x) for x in (offense,prevention,fielding,timezone,physics)]
    if any(x is None for x in vals):return None
    # Convert fractional component deltas into run-scale contributions. The
    # champion is approximately the all-ones coefficient vector before its cap.
    x=[pre*float(v) for v in vals];target=float(score)-pre
    return x,target,float(final_mu),float(score)


def _metrics(pairs:list[tuple[float,float]])->dict[str,Any]:
    if not pairs:return {"n":0,"mse":None,"mae":None}
    return {"n":len(pairs),"mse":sum((p-y)**2 for p,y in pairs)/len(pairs),"mae":sum(abs(p-y) for p,y in pairs)/len(pairs)}


def build(path:Path|str=PREDICTIONS)->dict[str,Any]:
    eligible=[r for r in _read(path) if r.get("settled") and r.get("model_generation")==MODEL_GENERATION and _policy(r)==PROBABILITY_POLICY_ID]
    canonical=select_canonical(eligible);rows=[phases["FINAL"] for phases in canonical.values() if "FINAL" in phases];rows.sort(key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or "")))
    games=[]
    for row in rows:
        hs=_team_sample(row,"home");aws=_team_sample(row,"away")
        if hs is not None and aws is not None:games.append((row,hs,aws))
    base={"schema":"pulsar-v14-residual-weight-challenger-v1","generated_at":datetime.now(timezone.utc).isoformat(),"model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"role":"CHALLENGER_ONLY","champion_impact":False,"auto_activation":False,"market_probability_used_as_feature":False,"network_calls":0,"phase":"FINAL","games":len(games),"minimum_games":MIN_GAMES,"ridge":RIDGE,"features":list(FEATURES)}
    if len(games)<MIN_GAMES:return {**base,"status":"COLLECTING","reason":f"games<{MIN_GAMES}"}
    cut=max(1,int(len(games)*.70));train=games[:cut];holdout=games[cut:];samples=[]
    for _row,home,away in train:samples.extend([(home[0],home[1]),(away[0],away[1])])
    beta=_fit(samples)
    if beta is None:return {**base,"status":"REJECTED_NUMERICAL"}
    champion=[];candidate=[]
    for _row,home,away in holdout:
        for sample in (home,away):
            x,target,final_mu,score=sample;pre=score-target;pred=max(.05,pre+beta[0]+sum(beta[i+1]*x[i] for i in range(len(FEATURES))))
            champion.append((final_mu,score));candidate.append((pred,score))
    cm=_metrics(champion);nm=_metrics(candidate);gain=(cm["mse"]-nm["mse"]) if cm["mse"] is not None and nm["mse"] is not None else None
    return {**base,"status":"NOMINATED_SHADOW" if gain is not None and gain>0 else "NO_IMPROVEMENT","chronological_split":{"train_games":len(train),"holdout_games":len(holdout)},"coefficients":{"intercept_runs":beta[0],**{name:beta[i+1] for i,name in enumerate(FEATURES)}},"champion":cm,"candidate":nm,"mse_gain":gain,"promotion_policy":"nomination only; preregistered fresh prospective probability validation and generation change required"}


def write(*,predictions:Path|str=PREDICTIONS,output:Path|str=OUTPUT)->dict[str,Any]:
    out=build(predictions);p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return out


def main()->None:
    ap=argparse.ArgumentParser(description="Learn V14 advanced residual component weights in shadow");ap.add_argument("--predictions",default=str(PREDICTIONS));ap.add_argument("--output",default=str(OUTPUT));args=ap.parse_args();out=write(predictions=args.predictions,output=args.output);print(json.dumps({"status":out.get("status"),"games":out.get("games"),"network_calls":0},sort_keys=True))

if __name__=="__main__":main()
