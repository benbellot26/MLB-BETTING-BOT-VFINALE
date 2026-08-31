from __future__ import annotations

"""Simple learned run-mean challenger for the heuristic champion projection.

It learns only a regularized affine remapping of persisted champion home/away
run means on chronological prospective data. This is intentionally modest: it
can reveal systematic over/under-confidence or cross-team double counting
without changing the champion or introducing new external data/API costs.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .snapshot_policy import select_canonical

PREDICTIONS=Path("data/v14_predictions.jsonl")
OUTPUT=Path("data/v14_learned_run_mean_candidate.json")
MIN_GAMES=600
RIDGE=10.0


def _num(v:Any)->float|None:
    try:x=float(v)
    except Exception:return None
    return x if math.isfinite(x) else None


def _read(path:Path|str)->list[dict[str,Any]]:
    p=Path(path)
    if not p.exists():return []
    out=[]
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:r=json.loads(line)
        except Exception:continue
        if isinstance(r,dict):out.append(r)
    return out


def _solve3(a:list[list[float]],b:list[float])->list[float]|None:
    m=[list(a[i])+[b[i]] for i in range(3)]
    for col in range(3):
        pivot=max(range(col,3),key=lambda r:abs(m[r][col]))
        if abs(m[pivot][col])<1e-10:return None
        m[col],m[pivot]=m[pivot],m[col]
        div=m[col][col];m[col]=[x/div for x in m[col]]
        for r in range(3):
            if r==col:continue
            factor=m[r][col];m[r]=[m[r][c]-factor*m[col][c] for c in range(4)]
    return [m[i][3] for i in range(3)]


def _fit(samples:list[tuple[float,float,float]],ridge:float=RIDGE)->list[float]|None:
    # y ~= beta0 + beta1*own_mu + beta2*opp_mu; intercept is not penalized.
    a=[[0.0]*3 for _ in range(3)];b=[0.0]*3
    for own,opp,y in samples:
        x=[1.0,own,opp]
        for i in range(3):
            b[i]+=x[i]*y
            for j in range(3):a[i][j]+=x[i]*x[j]
    a[1][1]+=ridge;a[2][2]+=ridge
    return _solve3(a,b)


def _predict(beta:list[float],own:float,opp:float)->float:
    return max(1.0,min(9.0,beta[0]+beta[1]*own+beta[2]*opp))


def _metrics(rows:list[tuple[float,float]])->dict[str,Any]:
    if not rows:return {"n":0,"mae":None,"mse":None}
    return {"n":len(rows),"mae":sum(abs(p-y) for p,y in rows)/len(rows),"mse":sum((p-y)**2 for p,y in rows)/len(rows)}


def build(path:Path|str=PREDICTIONS)->dict[str,Any]:
    settled=[r for r in _read(path) if r.get("settled")]
    canonical=select_canonical(settled)
    # FINAL is preferred; if absent for a game, do not silently mix phases.
    rows=[phases["FINAL"] for phases in canonical.values() if "FINAL" in phases]
    rows.sort(key=lambda r:(str(r.get("game_date") or ""),str(r.get("game_pk") or "")))
    usable=[]
    for r in rows:
        hm=_num(r.get("home_mu"));am=_num(r.get("away_mu"));hs=_num(r.get("home_score"));aws=_num(r.get("away_score"))
        if None not in (hm,am,hs,aws):usable.append((hm,am,hs,aws))
    base={"schema":"pulsar-v14-learned-run-mean-challenger-v1","generated_at":datetime.now(timezone.utc).isoformat(),"role":"CHALLENGER_ONLY","auto_activation":False,"champion_impact":False,"network_calls":0,"phase":"FINAL","minimum_games":MIN_GAMES,"ridge":RIDGE,"games":len(usable)}
    if len(usable)<MIN_GAMES:
        return {**base,"status":"COLLECTING","reason":f"games<{MIN_GAMES}"}
    cut=max(1,int(len(usable)*.70));train=usable[:cut];holdout=usable[cut:]
    home_beta=_fit([(h,a,hs) for h,a,hs,_aws in train]);away_beta=_fit([(a,h,aws) for h,a,_hs,aws in train])
    if home_beta is None or away_beta is None:return {**base,"status":"REJECTED_NUMERICAL"}
    base_home=[(h,hs) for h,_a,hs,_aws in holdout];base_away=[(a,aws) for _h,a,_hs,aws in holdout]
    learned_home=[(_predict(home_beta,h,a),hs) for h,a,hs,_aws in holdout];learned_away=[(_predict(away_beta,a,h),aws) for h,a,_hs,aws in holdout]
    bm=_metrics(base_home+base_away);lm=_metrics(learned_home+learned_away)
    return {**base,"status":"VALIDATED_SHADOW" if lm["mse"] is not None and bm["mse"] is not None and lm["mse"]<bm["mse"] else "NO_IMPROVEMENT","chronological_split":{"train_games":len(train),"holdout_games":len(holdout),"train_fraction":.70},"coefficients":{"home":home_beta,"away":away_beta},"baseline":bm,"candidate":lm,"mse_gain":(bm["mse"]-lm["mse"]) if bm["mse"] is not None and lm["mse"] is not None else None,"promotion_policy":"nomination only; preregistered prospective probability validation required before champion change"}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=OUTPUT)->dict[str,Any]:
    out=build(predictions);p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return out


def main()->None:
    ap=argparse.ArgumentParser(description="Learned V14 run-mean shadow challenger");ap.add_argument("--predictions",default=str(PREDICTIONS));ap.add_argument("--output",default=str(OUTPUT));args=ap.parse_args();out=write(args.predictions,args.output);print(json.dumps({"status":out.get("status"),"games":out.get("games"),"network_calls":0},sort_keys=True))

if __name__=="__main__":main()
