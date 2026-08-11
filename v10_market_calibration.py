#!/usr/bin/env python3
"""V10 market-specific calibration and validation.

Uses the prediction ledger only. Calibration is split by market and information
phase. Pushes are preserved; Platt scaling is applied to the conditional W/L
probability.
"""
import math

PHASES=("EARLY","LATE","FINAL")
MARKETS=("ML","RUNLINE","TOTAL")

def clamp(x,a=.001,b=.999):
    return max(a,min(b,float(x)))

def logloss(probs,ys):
    if not probs:return None
    return sum(-(y*math.log(clamp(p))+(1-y)*math.log(clamp(1-p))) for p,y in zip(probs,ys))/len(probs)

def brier(probs,ys):
    if not probs:return None
    return sum((p-y)**2 for p,y in zip(probs,ys))/len(probs)

def fit_platt(probs,ys,epochs=700,lr=.035,l2=.015):
    if len(probs)<8:return None
    a,b=1.0,0.0
    xs=[math.log(clamp(p)/(1-clamp(p))) for p in probs]
    n=len(xs)
    for _ in range(epochs):
        ga=gb=0.0
        for x,y in zip(xs,ys):
            z=max(-25,min(25,a*x+b));q=1/(1+math.exp(-z));e=q-y
            ga+=e*x;gb+=e
        ga=ga/n+l2*(a-1.0);gb=gb/n+l2*b
        a-=lr*ga;b-=lr*gb
    return (a,b)

def platt_predict(model,p):
    if not model:return clamp(p)
    a,b=model;x=math.log(clamp(p)/(1-clamp(p)))
    z=max(-25,min(25,a*x+b))
    return clamp(1/(1+math.exp(-z)))

def calibrate_tuple(model,pw,pp,pl):
    total=max(0.0,float(pw))+max(0.0,float(pp))+max(0.0,float(pl))
    if total<=0:return (.5,0,.5)
    pw,pp,pl=max(0.0,pw)/total,max(0.0,pp)/total,max(0.0,pl)/total
    nonpush=pw+pl
    if nonpush<=0:return (0.0,1.0,0.0)
    q=platt_predict(model,pw/nonpush)
    mass=1-pp
    return (mass*q,pp,mass*(1-q))

def _iter_predictions(hist):
    for game_key,record in (hist or {}).items():
        for p in record.get("predictions",[]) or []:
            row=dict(p);row.setdefault("game_key",game_key);yield row
        if not record.get("predictions"):
            for snap in record.get("snapshots",[]) or []:
                for p in snap.get("predictions",[]) or []:
                    row=dict(p);row.setdefault("game_key",game_key);yield row

def settled_rows(hist,market=None,phase=None):
    rows=[]
    for p in _iter_predictions(hist):
        if market and p.get("market")!=market:continue
        if phase and p.get("phase")!=phase:continue
        result=p.get("result")
        if result not in ("W","L","P"):continue
        rows.append(p)
    rows.sort(key=lambda x:(x.get("analyzed_at",""),x.get("prediction_id","")))
    return rows

def metrics(rows):
    wl=[r for r in rows if r.get("result") in ("W","L")]
    probs=[clamp(r.get("p_model",.5)) for r in wl]
    ys=[1 if r["result"]=="W" else 0 for r in wl]
    return {"n":len(rows),"n_wl":len(wl),"pushes":len(rows)-len(wl),"brier":brier(probs,ys),"logloss":logloss(probs,ys),"accuracy":(sum((p>=.5)==bool(y) for p,y in zip(probs,ys))/len(wl) if wl else None)}

def calibration_state(hist,market,phase,min_games=500):
    rows=settled_rows(hist,market,phase);wl=[r for r in rows if r.get("result") in ("W","L")]
    base={"market":market,"phase":phase,"n":len(wl),"active":False,"model":None,"brier_raw":None,"brier_cal":None,"logloss_raw":None,"logloss_cal":None}
    if len(wl)<max(40,min_games):return base
    cut=max(30,int(len(wl)*.80));train,val=wl[:cut],wl[cut:]
    if len(val)<20:return base
    tp=[clamp(r.get("p_model_raw",r.get("p_model",.5))) for r in train];ty=[1 if r["result"]=="W" else 0 for r in train]
    vp=[clamp(r.get("p_model_raw",r.get("p_model",.5))) for r in val];vy=[1 if r["result"]=="W" else 0 for r in val]
    model=fit_platt(tp,ty);cal=[platt_predict(model,p) for p in vp]
    br0,br1=brier(vp,vy),brier(cal,vy);ll0,ll1=logloss(vp,vy),logloss(cal,vy)
    active=(br1 is not None and ll1 is not None and br1<=br0*.997 and ll1<=ll0*.997)
    full_model=fit_platt([clamp(r.get("p_model_raw",r.get("p_model",.5))) for r in wl],[1 if r["result"]=="W" else 0 for r in wl]) if active else None
    base.update({"active":active,"model":full_model,"brier_raw":br0,"brier_cal":br1,"logloss_raw":ll0,"logloss_cal":ll1});return base

def build_states(hist,min_games=500):
    return {phase:{market:calibration_state(hist,market,phase,min_games) for market in MARKETS} for phase in PHASES}

def reliability_buckets(hist,market=None,phase=None):
    rows=[r for r in settled_rows(hist,market,phase) if r.get("result") in ("W","L")];out=[]
    for lo in (.50,.55,.60,.65,.70,.75,.80,.85,.90):
        hi=lo+.05;xs=[r for r in rows if lo<=float(r.get("p_model",.5))<hi]
        if xs:out.append({"lo":lo,"hi":hi,"n":len(xs),"pred":sum(float(x.get("p_model",.5)) for x in xs)/len(xs),"actual":sum(x["result"]=="W" for x in xs)/len(xs)})
    return out

def self_test():
    pw,pp,pl=calibrate_tuple((1.0,0.0),.55,.08,.37);assert abs(pp-.08)<1e-9 and abs(pw+pp+pl-1)<1e-9
    hist={};preds=[]
    for i in range(600):
        p=.70 if i%2==0 else .62;y=(i%10)<6
        preds.append({"prediction_id":str(i),"market":"ML","phase":"EARLY","p_model_raw":p,"p_model":p,"result":"W" if y else "L","analyzed_at":f"2026-01-{(i%28)+1:02d}T00:00:{i%60:02d}Z"})
    hist["g"]={"predictions":preds};st=calibration_state(hist,"ML","EARLY",500);assert st["n"]==600
    m=metrics(settled_rows(hist,"ML","EARLY"));assert m["n_wl"]==600 and m["brier"] is not None and m["logloss"] is not None
    assert calibration_state(hist,"TOTAL","EARLY",500)["n"]==0 and calibration_state(hist,"ML","FINAL",500)["n"]==0
    print("SELF-TEST V10 MARKET CALIBRATION OK",st,m)
if __name__=="__main__":self_test()
