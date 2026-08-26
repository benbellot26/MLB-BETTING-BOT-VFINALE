from __future__ import annotations

"""Causal run-residual challenger with paired chronological OOS promotion gates.

Each observation is one offense facing the opponent starter/bullpen. One shared
ridge model is trained on both sides of each training game; games never straddle
train and holdout. Promotion requires statistically robust run-error improvement
and market-level non-regression. Integer-total pushes are excluded.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .distribution import probability_surface
from .model import RunProjection
from .tracking import _canonical_settled, _read_jsonl

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_residual_challenger.json")
MIN_GAMES=600
MIN_HOLDOUT_GAMES=100
RIDGE=16.0
MAX_RUN_DELTA=.55
MARKETS=("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER")

FEATURE_NAMES=(
    "is_home","off_lineup_ops","off_lineup_coverage","off_xwoba","off_hard_hit","off_barrel","off_k_minus_bb",
    "opp_starter_era","opp_starter_whip","opp_starter_k9","opp_starter_bb9","opp_starter_hr9","opp_starter_sample_weight",
    "opp_starter_xwoba","opp_starter_hard_hit","opp_starter_barrel","opp_starter_k_minus_bb","opp_expected_starter_ip",
    "opp_bullpen_taxed_rate","opp_bullpen_unavailable_rate","opp_bullpen_mean_pitches3","opp_bullpen_xwoba","opp_bullpen_k_minus_bb",
    "off_rest_days","off_travel_1000km","off_timezone_shift_exact","off_previous_extra_innings","temperature_centered","wind_mph",
)


def _num(v:Any,default:float|None=None)->float|None:
    try: out=float(v)
    except Exception: return default
    return out if math.isfinite(out) else default

def _neutral(v:Any,default:float)->float:
    x=_num(v); return float(default if x is None else x)

def _statcast_side(tf:dict[str,Any],side:str)->dict[str,Any]: return ((tf.get("statcast_shadow") or {}).get(side) or {})


def _bullpen_summary(tf:dict[str,Any],side:str)->tuple[float,float,float]:
    bullpen=((tf.get("bullpen") or {}).get(side) or {}); relievers=[r for r in bullpen.get("relievers") or [] if isinstance(r,dict)]
    if not relievers: return 0.0,0.0,0.0
    n=len(relievers); taxed=sum(bool(r.get("taxed")) for r in relievers)/n; unavailable=sum(r.get("likely_unavailable") is True or r.get("available") is False for r in relievers)/n; pitches=[_num(r.get("pitches_last_3d")) for r in relievers]; pitches=[x for x in pitches if x is not None]
    return taxed,unavailable,(sum(pitches)/len(pitches) if pitches else 0.0)


def offense_vs_opponent_features(row:dict[str,Any],offense_side:str)->list[float]|None:
    tf=row.get("training_features") or {}
    if tf.get("point_in_time") is not True: return None
    opponent="away" if offense_side=="home" else "home"; off_lineup=tf.get(f"{offense_side}_lineup") or {}; opp_starter=tf.get(f"{opponent}_starter") or {}; off_oper=((tf.get("operational") or {}).get(offense_side) or {}); env=tf.get("environment") or {}; off_sc=_statcast_side(tf,offense_side); opp_sc=_statcast_side(tf,opponent); off_sc_lineup=off_sc.get("lineup") or {}; opp_sc_starter=opp_sc.get("starter") or {}; opp_sc_bullpen=opp_sc.get("bullpen") or {}; taxed,unavailable,mean_pitches=_bullpen_summary(tf,opponent); challengers=tf.get("research_challengers") or {}; usage=challengers.get(f"{opponent}_starter_usage") or {}; tz=_num(off_oper.get("timezone_shift_hours_exact")); tz=tz if tz is not None else _num(off_oper.get("timezone_shift_hours_approx"),0.0)
    return [1.0 if offense_side=="home" else 0.0,_neutral(off_lineup.get("weighted_ops"),.725),_neutral(off_lineup.get("coverage"),0.0),_neutral(off_sc_lineup.get("xwoba"),.320),_neutral(off_sc_lineup.get("hard_hit_rate"),.38),_neutral(off_sc_lineup.get("barrel_rate"),.08),_neutral(off_sc_lineup.get("k_minus_bb_rate"),.12),_neutral(opp_starter.get("era"),4.35),_neutral(opp_starter.get("whip"),1.32),_neutral(opp_starter.get("k9"),8.5),_neutral(opp_starter.get("bb9"),3.2),_neutral(opp_starter.get("hr9"),1.15),_neutral(opp_starter.get("sample_weight"),0.0),_neutral(opp_sc_starter.get("xwoba_allowed"),.320),_neutral(opp_sc_starter.get("hard_hit_rate_allowed"),.38),_neutral(opp_sc_starter.get("barrel_rate_allowed"),.08),_neutral(opp_sc_starter.get("k_minus_bb_rate"),.12),_neutral(usage.get("expected_innings"),5.2),taxed,unavailable,mean_pitches,_neutral(opp_sc_bullpen.get("xwoba_allowed"),.320),_neutral(opp_sc_bullpen.get("k_minus_bb_rate"),.12),_neutral(off_oper.get("rest_days"),0.0),_neutral(off_oper.get("travel_km"),0.0)/1000.0,abs(float(tz or 0.0)),1.0 if off_oper.get("previous_extra_innings") else 0.0,(_neutral(env.get("temperature_f"),70.0)-70.0)/20.0,_neutral(env.get("wind_mph"),0.0)/15.0]


def _standardize(xs:list[list[float]])->tuple[list[list[float]],list[float],list[float]]:
    d=len(xs[0]); means=[sum(r[j] for r in xs)/len(xs) for j in range(d)]; std=[max(1e-6,math.sqrt(sum((r[j]-means[j])**2 for r in xs)/max(1,len(xs)-1))) for j in range(d)]; return [[(r[j]-means[j])/std[j] for j in range(d)] for r in xs],means,std


def _solve(a:list[list[float]],b:list[float])->list[float]:
    n=len(b); m=[a[i][:]+[b[i]] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(m[r][col])); m[col],m[pivot]=m[pivot],m[col]
        if abs(m[col][col])<1e-10: continue
        div=m[col][col]; m[col]=[v/div for v in m[col]]
        for r in range(n):
            if r==col: continue
            f=m[r][col]
            if f: m[r]=[m[r][c]-f*m[col][c] for c in range(n+1)]
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
    value=float(model["intercept"])
    for i,name in enumerate(FEATURE_NAMES): value+=float(model["coefficients"][name])*(x[i]-float(model["means"][name]))/float(model["std"][name])
    return max(-MAX_RUN_DELTA,min(MAX_RUN_DELTA,value))


def _game_predictions(row:dict[str,Any],model:dict[str,Any]|None)->dict[str,Any]|None:
    hf=offense_vs_opponent_features(row,"home"); af=offense_vs_opponent_features(row,"away"); hmu=_num(row.get("home_mu")); amu=_num(row.get("away_mu")); line=_num(row.get("total_line"))
    if hf is None or af is None or None in {hmu,amu,line}: return None
    hm=max(.2,float(hmu)+(_predict(model,hf) if model else 0)); am=max(.2,float(amu)+(_predict(model,af) if model else 0)); hs=int(row["home_score"]); aws=int(row["away_score"]); proj=RunProjection(game_pk=str(row.get("game_pk") or "x"),game_date=str(row.get("game_date") or ""),analyzed_at=str(row.get("analyzed_at") or ""),home=str(row.get("home") or "H"),away=str(row.get("away") or "A"),home_mu=hm,away_mu=am,total_line=float(line)); surf,_=probability_surface(proj); total=hs+aws
    outcomes={"ML":int(hs>aws),"RL_HOME_-1.5":int(hs-aws>=2),"RL_AWAY_-1.5":int(aws-hs>=2),"TOTAL_OVER":None if abs(total-float(line))<1e-9 else int(total>float(line))}; probs={"ML":surf.home_ml,"RL_HOME_-1.5":surf.home_minus_1_5,"RL_AWAY_-1.5":surf.away_minus_1_5,"TOTAL_OVER":surf.over}
    return {"home_abs_error":abs(hm-hs),"away_abs_error":abs(am-aws),"total_abs_error":abs(hm+am-total),"markets":{m:(float(probs[m]),outcomes[m]) for m in MARKETS if outcomes[m] is not None}}


def _mean_ci(values:list[float])->dict[str,Any]:
    if not values: return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None}
    mean=sum(values)/len(values)
    if len(values)<2: return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None}
    var=sum((v-mean)**2 for v in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-1.96*se,"ci95_upper":mean+1.96*se}


def _paired_metrics(rows:list[dict[str,Any]],model:dict[str,Any])->dict[str,Any]:
    eps=1e-12; team_gain=[]; total_gain=[]; market_diffs={m:{"brier":[],"logloss":[]} for m in MARKETS}; used=0
    for row in rows:
        champion=_game_predictions(row,None); candidate=_game_predictions(row,model)
        if champion is None or candidate is None: continue
        used+=1; team_gain.extend((champion["home_abs_error"]-candidate["home_abs_error"],champion["away_abs_error"]-candidate["away_abs_error"])); total_gain.append(champion["total_abs_error"]-candidate["total_abs_error"])
        for market in MARKETS:
            if market not in champion["markets"] or market not in candidate["markets"]: continue
            hp,y=champion["markets"][market]; cp,cy=candidate["markets"][market]
            if y!=cy: continue
            market_diffs[market]["brier"].append((hp-y)**2-(cp-y)**2); hl=-(y*math.log(max(eps,min(1-eps,hp)))+(1-y)*math.log(max(eps,min(1-eps,1-hp)))); cl=-(y*math.log(max(eps,min(1-eps,cp)))+(1-y)*math.log(max(eps,min(1-eps,1-cp)))); market_diffs[market]["logloss"].append(hl-cl)
    return {"games":used,"team_run_mae_gain":_mean_ci(team_gain),"total_run_mae_gain":_mean_ci(total_gain),"markets":{m:{"brier_gain":_mean_ci(v["brier"]),"logloss_gain":_mean_ci(v["logloss"]),"pushes_excluded":m=="TOTAL_OVER"} for m,v in market_diffs.items()}}


def build(rows:list[dict[str,Any]])->dict[str,Any]:
    settled,_=_canonical_settled(rows); usable=[r for r in settled if offense_vs_opponent_features(r,"home") is not None and offense_vs_opponent_features(r,"away") is not None]; n=len(usable); base={"schema":"pulsar-v14-run-residual-challenger-v3","role":"CHALLENGER_ONLY","auto_activation":False,"games":n,"observations":2*n,"minimum_games":MIN_GAMES,"feature_names":list(FEATURE_NAMES),"causal_contract":"scoring offense features + opponent starter/bullpen features; one shared side model","paired_holdout_inference":True}
    if n<MIN_GAMES: return {**base,"status":"COLLECTING","reason":"insufficient_pit_feature_rows"}
    split=int(n*.80); train,holdout=usable[:split],usable[split:]
    if len(holdout)<MIN_HOLDOUT_GAMES: return {**base,"status":"COLLECTING","reason":"holdout_too_small"}
    xs=[]; ys=[]
    for row in train:
        h=offense_vs_opponent_features(row,"home"); a=offense_vs_opponent_features(row,"away"); hmu=_num(row.get("home_mu")); amu=_num(row.get("away_mu"))
        if h is None or a is None or hmu is None or amu is None: continue
        xs.extend((h,a)); ys.extend((float(row["home_score"])-hmu,float(row["away_score"])-amu))
    if not xs: return {**base,"status":"COLLECTING","reason":"no_training_observations"}
    model=_fit(xs,ys); paired=_paired_metrics(holdout,model); team=paired["team_run_mae_gain"]; total=paired["total_run_mae_gain"]; market_nonreg=True
    for market,row in paired["markets"].items():
        b=row["brier_gain"]; l=row["logloss_gain"]
        if int(b.get("n") or 0)<MIN_HOLDOUT_GAMES or b.get("ci95_lower") is None or float(b["ci95_lower"])<-.0015: market_nonreg=False
        if int(l.get("n") or 0)<MIN_HOLDOUT_GAMES or l.get("ci95_lower") is None or float(l["ci95_lower"])<-.003: market_nonreg=False
    passes=bool(int(team.get("n") or 0)>=2*MIN_HOLDOUT_GAMES and team.get("ci95_lower") is not None and float(team["ci95_lower"])>0 and total.get("ci95_lower") is not None and float(total["ci95_lower"])>=-.02 and market_nonreg)
    return {**base,"status":"PROMOTION_ELIGIBLE" if passes else "REJECTED_OOS","passes":passes,"model":model,"train_games":len(train),"holdout_games":len(holdout),"paired_holdout":paired,"per_market_nonregression":market_nonreg,"promotion_gate":"paired team-run MAE gain CI95 lower >0; total-run MAE lower >= -0.02; each market Brier lower >= -0.0015 and LogLoss lower >= -0.003","note":"Never loaded by production automatically; promotion requires deliberate versioned champion change."}


def write(predictions:Path|str=PREDICTIONS,output:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build(_read_jsonl(predictions)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact


def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write(args.predictions,args.output); print(f"PULSAR_V14_RESIDUAL_CHALLENGER status={artifact.get('status')} games={artifact.get('games')}")

if __name__=="__main__": main()
