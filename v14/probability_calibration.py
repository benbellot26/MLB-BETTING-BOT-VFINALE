from __future__ import annotations

"""Leakage-safe probability calibration for Pulsar V14.

MARKET calibrators use the latest strictly-pregame snapshot per game; PHASE
calibrators use the latest per (game, phase). A transform is applied only after
statistically significant paired improvement on untouched chronological holdout.
A naturally calibrated raw surface may instead earn VALIDATED_IDENTITY. Integer
Total pushes are excluded from binary calibration. Evidence is fail-closed to
the exact current model generation and probability policy.
"""

from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID

PREDICTIONS=Path("data/v14_predictions.jsonl")
ARTIFACT=Path("data/v14_calibration.json")
MIN_MARKET_OBSERVATIONS=400
MIN_PHASE_OBSERVATIONS=300
MIN_HOLDOUT=80
HOLDOUT_FRACTION=.20
L2=2.0
EPS=1e-9
IDENTITY_MAX_ECE=.05
IDENTITY_SLOPE_RANGE=(.80,1.20)
IDENTITY_MAX_INTERCEPT=.25
CANONICAL_MARKETS={"ML":"home_ml","RL_HOME_-1.5":"home_minus_1_5","RL_AWAY_-1.5":"away_minus_1_5","TOTAL_OVER":"over"}
PAIR_MAP={"home_ml":("home_ml","away_ml","ML"),"home_minus_1_5":("home_minus_1_5","away_plus_1_5","RL_HOME_-1.5"),"away_minus_1_5":("away_minus_1_5","home_plus_1_5","RL_AWAY_-1.5"),"over":("over","under","TOTAL_OVER")}


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None
def _clip(p:float)->float: return min(1-EPS,max(EPS,float(p)))
def _logit(p:float)->float:
    q=_clip(p); return math.log(q/(1-q))
def _sigmoid(z:float)->float:
    if z>=0:
        e=math.exp(-z); return 1/(1+e)
    e=math.exp(z); return e/(1+e)


def _parse_time(value:Any)->datetime|None:
    if not value: return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"));
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception: return None
def _time_key(row:dict[str,Any])->tuple[datetime,datetime,str]:
    minimum=datetime.min.replace(tzinfo=timezone.utc); return (_parse_time(row.get("game_date")) or minimum,_parse_time(row.get("analyzed_at")) or minimum,str(row.get("game_pk") or ""))
def _read_jsonl(path:Path|str)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists(): return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict): rows.append(row)
    return rows
def _strictly_pregame(row:dict[str,Any])->bool:
    at=_parse_time(row.get("analyzed_at")); game=_parse_time(row.get("game_date")); return bool(at and game and at<game)
def _eligible_rows(rows:list[dict[str,Any]])->list[dict[str,Any]]:
    return [r for r in rows if r.get("model_generation")==MODEL_GENERATION and r.get("probability_policy_id")==PROBABILITY_POLICY_ID and r.get("settled") and _strictly_pregame(r) and str(r.get("game_pk") or "")]
def _latest_settled_by_game(rows:list[dict[str,Any]])->list[dict[str,Any]]:
    latest={}
    for row in _eligible_rows(rows):
        key=str(row.get("game_pk")); cur=latest.get(key)
        if cur is None or _time_key(row)[1]>_time_key(cur)[1]: latest[key]=row
    return sorted(latest.values(),key=_time_key)
def _latest_settled_by_game_phase(rows:list[dict[str,Any]])->list[dict[str,Any]]:
    latest={}
    for row in _eligible_rows(rows):
        phase=str(row.get("phase") or "EARLY").upper()
        if phase not in {"EARLY","LATE","FINAL"}: continue
        key=(str(row.get("game_pk")),phase); cur=latest.get(key)
        if cur is None or _time_key(row)[1]>_time_key(cur)[1]: latest[key]=row
    return sorted(latest.values(),key=_time_key)


def _outcome(row:dict[str,Any],market:str)->int|None:
    hs=_num(row.get("home_score")); aws=_num(row.get("away_score"))
    if hs is None or aws is None: return None
    if market=="ML": return int(hs>aws)
    if market=="RL_HOME_-1.5": return int(hs-aws>=2)
    if market=="RL_AWAY_-1.5": return int(aws-hs>=2)
    if market=="TOTAL_OVER":
        line=_num(row.get("total_line"))
        if line is None: return None
        total=hs+aws
        if abs(total-line)<1e-9: return None
        return int(total>line)
    return None
def _items(rows:list[dict[str,Any]],market:str)->list[tuple[float,int]]:
    key=CANONICAL_MARKETS[market]; out=[]
    for row in rows:
        probs=row.get("raw_probabilities") or row.get("probabilities") or {}; p=_num(probs.get(key)); y=_outcome(row,market)
        if p is not None and y is not None and 0<p<1: out.append((float(p),int(y)))
    return out
def observations(rows:list[dict[str,Any]])->dict[str,list[tuple[float,int,str]]]:
    out=defaultdict(list)
    for row in _latest_settled_by_game(rows):
        phase=str(row.get("phase") or "EARLY").upper(); probs=row.get("raw_probabilities") or row.get("probabilities") or {}
        for market,key in CANONICAL_MARKETS.items():
            p=_num(probs.get(key)); y=_outcome(row,market)
            if p is not None and y is not None and 0<p<1: out[market].append((float(p),int(y),phase))
    return dict(out)


def _calibration_bins(items:list[tuple[float,int]],bins:int=10)->list[dict[str,Any]]:
    grouped=[[] for _ in range(bins)]
    for p,y in items: grouped[min(bins-1,max(0,int(p*bins)))].append((p,y))
    return [{"lower":i/bins,"upper":(i+1)/bins,"n":len(v),"mean_probability":sum(p for p,_ in v)/len(v),"observed_rate":sum(y for _,y in v)/len(v)} for i,v in enumerate(grouped) if v]
def _scores(items:list[tuple[float,int]])->dict[str,float|int|None]:
    if not items: return {"n":0,"brier":None,"log_loss":None,"mean_probability":None,"observed_rate":None,"ece":None}
    eps=1e-12; bins=_calibration_bins(items); brier=sum((p-y)**2 for p,y in items)/len(items); ll=-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items); ece=sum(r["n"]/len(items)*abs(r["mean_probability"]-r["observed_rate"]) for r in bins)
    return {"n":len(items),"brier":brier,"log_loss":ll,"mean_probability":sum(p for p,_ in items)/len(items),"observed_rate":sum(y for _,y in items)/len(items),"ece":ece}
def _mean_ci(values:list[float])->dict[str,Any]:
    if not values: return {"n":0,"mean":None,"ci95_lower":None,"ci95_upper":None}
    mean=sum(values)/len(values)
    if len(values)<2: return {"n":len(values),"mean":mean,"ci95_lower":None,"ci95_upper":None}
    var=sum((x-mean)**2 for x in values)/(len(values)-1); se=math.sqrt(var/len(values)); return {"n":len(values),"mean":mean,"ci95_lower":mean-1.96*se,"ci95_upper":mean+1.96*se}
def _paired_transform_gain(raw_items:list[tuple[float,int]],cal_items:list[tuple[float,int]])->dict[str,Any]:
    eps=1e-12; bd=[]; ld=[]
    for (rp,y),(cp,cy) in zip(raw_items,cal_items):
        if y!=cy: continue
        bd.append((rp-y)**2-(cp-y)**2); rl=-(y*math.log(max(eps,min(1-eps,rp)))+(1-y)*math.log(max(eps,min(1-eps,1-rp)))); cl=-(y*math.log(max(eps,min(1-eps,cp)))+(1-y)*math.log(max(eps,min(1-eps,1-cp)))); ld.append(rl-cl)
    return {"brier":_mean_ci(bd),"logloss":_mean_ci(ld)}


def _fit_platt(items:list[tuple[float,int]],*,l2:float=L2)->tuple[float,float]:
    a,b=1.0,0.0
    for _ in range(60):
        gaa=gab=gbb=ga=gb=0.0
        for p,y in items:
            x=_logit(p); q=_sigmoid(a*x+b); w=max(1e-8,q*(1-q)); err=q-y; ga+=err*x; gb+=err; gaa+=w*x*x; gab+=w*x; gbb+=w
        ga+=l2*(a-1); gb+=l2*b; gaa+=l2; gbb+=l2; det=gaa*gbb-gab*gab
        if abs(det)<1e-12: break
        da=(gbb*ga-gab*gb)/det; db=(-gab*ga+gaa*gb)/det; scale=max(1.0,abs(da)/.25,abs(db)/.25); a-=da/scale; b-=db/scale
        if max(abs(da/scale),abs(db/scale))<1e-7: break
    return float(a),float(b)
def _identity_diagnostics(holdout:list[tuple[float,int]])->dict[str,Any]:
    raw=_scores(holdout); slope,intercept=_fit_platt(holdout,l2=.25); accepted=bool(raw.get("ece") is not None and float(raw["ece"])<=IDENTITY_MAX_ECE and IDENTITY_SLOPE_RANGE[0]<=slope<=IDENTITY_SLOPE_RANGE[1] and abs(intercept)<=IDENTITY_MAX_INTERCEPT); return {"accepted":accepted,"slope":slope,"intercept":intercept,"ece":raw.get("ece"),"metrics":raw}


def _fit_one(items:list[tuple[float,int]],*,minimum_n:int)->dict[str,Any]:
    n=len(items); base={"active":False,"accepted":False,"method":"identity","n":n,"minimum_n":minimum_n,"slope":1.0,"intercept":0.0}; holdout_n=max(MIN_HOLDOUT,int(round(n*HOLDOUT_FRACTION))); train_n=n-holdout_n
    if n<minimum_n or train_n<200 or holdout_n<MIN_HOLDOUT: return {**base,"status":"COLLECTING","reason":"insufficient_chronological_evidence"}
    train,holdout=items[:train_n],items[train_n:]; a,b=_fit_platt(train); raw=_scores(holdout); transformed=[(_sigmoid(a*_logit(p)+b),y) for p,y in holdout]; cal=_scores(transformed); gains=_paired_transform_gain(holdout,transformed); brier_gain=float(raw["brier"])-float(cal["brier"]); logloss_gain=float(raw["log_loss"])-float(cal["log_loss"]); stable=.45<=a<=1.75 and abs(b)<=1.25; bg=gains["brier"]; lg=gains["logloss"]; active=bool(stable and int(bg.get("n") or 0)>=MIN_HOLDOUT and bg.get("ci95_lower") is not None and float(bg["ci95_lower"])>0 and lg.get("ci95_lower") is not None and float(lg["ci95_lower"])>=-.001); identity=_identity_diagnostics(holdout)
    common={"candidate_slope":a,"candidate_intercept":b,"train_n":train_n,"holdout_n":holdout_n,"raw_holdout":raw,"calibrated_holdout":cal,"identity_diagnostics":identity,"brier_gain":brier_gain,"logloss_gain":logloss_gain,"paired_gain_ci95":gains,"stable_parameters":stable}
    if active: return {**base,**common,"active":True,"accepted":True,"method":"platt-logit","status":"ACTIVE_TRANSFORM","slope":a,"intercept":b,"reason":"paired_oos_transform_gain_ci95"}
    if identity["accepted"]: return {**base,**common,"accepted":True,"status":"VALIDATED_IDENTITY","calibrated_holdout":raw,"brier_gain":0.0,"logloss_gain":0.0,"reason":"raw_probabilities_already_calibrated_oos"}
    return {**base,**common,"status":"REJECTED_OOS","reason":"neither_significant_transform_nor_identity_passed_oos_gate"}


def build_artifact(rows:list[dict[str,Any]])->dict[str,Any]:
    eligible=_eligible_rows(rows); excluded_policy=sum(1 for r in rows if r.get("settled") and r.get("model_generation")==MODEL_GENERATION and r.get("probability_policy_id")!=PROBABILITY_POLICY_ID)
    market_rows=_latest_settled_by_game(eligible); phase_rows=_latest_settled_by_game_phase(eligible); calibrators={}
    for market in CANONICAL_MARKETS:
        calibrators[f"MARKET:{market}"]=_fit_one(_items(market_rows,market),minimum_n=MIN_MARKET_OBSERVATIONS)
        for phase in ("EARLY","LATE","FINAL"):
            scoped=[r for r in phase_rows if str(r.get("phase") or "EARLY").upper()==phase]; calibrators[f"PHASE:{phase}:{market}"]=_fit_one(_items(scoped,market),minimum_n=MIN_PHASE_OBSERVATIONS)
    latest=_time_key(market_rows[-1])[0].isoformat() if market_rows else None
    return {"schema":"pulsar-v14-calibration-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":datetime.now(timezone.utc).isoformat(),"latest_observation_at":latest,"eligible_current_policy_rows":len(eligible),"excluded_other_policy_rows":excluded_policy,"strictly_pregame":True,"chronological_holdout":True,"chronological_order":"game_date_utc_then_analyzed_at","market_snapshot_policy":"latest strictly-pregame snapshot per game","phase_snapshot_policy":"latest strictly-pregame snapshot per (game, phase)","total_push_policy":"exclude pushes from binary calibration","market_probability_used_as_feature":False,"calibrators":calibrators,"policy":{"market_min_n":MIN_MARKET_OBSERVATIONS,"phase_min_n":MIN_PHASE_OBSERVATIONS,"exact_probability_policy_required":True,"transform_activation":"paired holdout Brier gain CI95 lower >0 + LogLoss lower >= -0.001 + stable parameters","identity_acceptance":"holdout ECE<=0.05, slope 0.80..1.20, |intercept|<=0.25"}}


def _empty_artifact()->dict[str,Any]: return {"schema":"pulsar-v14-calibration-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"calibrators":{}}
def _validated_artifact(payload:Any)->dict[str,Any]:
    if not isinstance(payload,dict): return _empty_artifact()
    if payload.get("schema")!="pulsar-v14-calibration-v3" or payload.get("model_generation")!=MODEL_GENERATION or payload.get("probability_policy_id")!=PROBABILITY_POLICY_ID: return _empty_artifact()
    return payload
def load_artifact(path:Path|str=ARTIFACT)->dict[str,Any]:
    target=Path(path)
    if not target.exists(): return _empty_artifact()
    try: payload=json.loads(target.read_text(encoding="utf-8"))
    except Exception: return _empty_artifact()
    return _validated_artifact(payload)
def _accepted(cal:dict[str,Any])->bool: return cal.get("accepted") is True or cal.get("active") is True
def _select_calibrator(artifact:dict[str,Any],market:str,phase:str)->tuple[str,dict[str,Any]]:
    calibrators=artifact.get("calibrators") or {}; phase_key=f"PHASE:{str(phase).upper()}:{market}"; market_key=f"MARKET:{market}"; phase_cal=calibrators.get(phase_key) or {}
    if _accepted(phase_cal): return phase_key,phase_cal
    market_cal=calibrators.get(market_key) or {}
    if _accepted(market_cal): return market_key,market_cal
    return market_key,market_cal or {"active":False,"accepted":False,"method":"identity","n":0,"minimum_n":MIN_MARKET_OBSERVATIONS}
def calibrate_probability(p:float,market:str,phase:str,artifact:dict[str,Any]|None=None)->tuple[float,dict[str,Any]]:
    data=load_artifact() if artifact is None else _validated_artifact(artifact); key,cal=_select_calibrator(data,market,phase)
    common={"probability_policy_id":PROBABILITY_POLICY_ID,"artifact_generated_at":data.get("generated_at"),"artifact_latest_observation_at":data.get("latest_observation_at")}
    if cal.get("active") is not True: return float(p),{**common,"active":False,"accepted":_accepted(cal),"key":key,"method":"identity","n":int(cal.get("n") or 0),"status":str(cal.get("status") or "COLLECTING"),"holdout":cal.get("raw_holdout") or {}}
    a=_num(cal.get("slope")); b=_num(cal.get("intercept"))
    if a is None or b is None: return float(p),{**common,"active":False,"accepted":False,"key":key,"method":"identity","n":int(cal.get("n") or 0),"status":"INVALID_ARTIFACT"}
    return _sigmoid(a*_logit(_clip(p))+b),{**common,"active":True,"accepted":True,"key":key,"method":"platt-logit","n":int(cal.get("n") or 0),"slope":a,"intercept":b,"status":str(cal.get("status") or "ACTIVE_TRANSFORM"),"holdout":cal.get("calibrated_holdout") or {}}
def calibrate_surface(probabilities:dict[str,Any],*,phase:str,artifact:dict[str,Any]|None=None)->tuple[dict[str,float],dict[str,Any]]:
    data=load_artifact() if artifact is None else _validated_artifact(artifact); surface={k:float(v) for k,v in probabilities.items() if _num(v) is not None}; details={}
    for canonical_key,(left,right,market) in PAIR_MAP.items():
        if canonical_key not in surface or right not in surface: continue
        q,meta=calibrate_probability(surface[canonical_key],market,phase,data); q=min(1.0,max(0.0,q)); surface[left]=q; surface[right]=1-q; details[market]=meta
    return surface,{"schema":"pulsar-v14-calibration-application-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"artifact_schema":data.get("schema"),"artifact_generated_at":data.get("generated_at"),"artifact_latest_observation_at":data.get("latest_observation_at"),"phase":str(phase).upper(),"markets":details,"any_active":any(v.get("active") for v in details.values()),"all_accepted":bool(details) and all(v.get("accepted") for v in details.values())}
def write_artifact(predictions:Path|str=PREDICTIONS,destination:Path|str=ARTIFACT)->dict[str,Any]:
    artifact=build_artifact(_read_jsonl(predictions)); target=Path(destination); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return artifact
def main()->None:
    parser=argparse.ArgumentParser(description="Fit leakage-safe Pulsar V14 probability calibrators"); parser.add_argument("command",choices=["fit"]); parser.add_argument("--predictions",default=str(PREDICTIONS)); parser.add_argument("--output",default=str(ARTIFACT)); args=parser.parse_args(); artifact=write_artifact(args.predictions,args.output); active=sum(bool(v.get("active")) for v in artifact.get("calibrators",{}).values()); accepted=sum(bool(v.get("accepted")) for v in artifact.get("calibrators",{}).values()); print(f"PULSAR_V14_CALIBRATION active={active} accepted={accepted} output={args.output}")

if __name__=="__main__": main()
