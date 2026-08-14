from __future__ import annotations
import math
from .models import logit, sigmoid, clamp
from .validation import evaluate_probability_challenger, production_gate, brier, logloss

def _num(x,d=0.0):
    try:
        y=float(x); return y if math.isfinite(y) else d
    except Exception:return d

def _norm(s):return "".join(c.lower() for c in str(s or "") if c.isalnum())

def _market_target(row,item):
    if row.get("result_status")!="FINAL":return None
    hs,aps=_num(row.get("home_score")),_num(row.get("away_score")); home,away=str(row.get("home")),str(row.get("away")); market=str(item.get("market") or "").upper(); pick=str(item.get("pick") or ""); point=_num(item.get("point"))
    if market=="RUNLINE":
        margin=hs-aps+point if _norm(pick)==_norm(home) else aps-hs+point if _norm(pick)==_norm(away) else None
        if margin is None or abs(margin)<=1e-9:return None
        return 1 if margin>0 else 0
    if market=="TOTAL":
        diff=hs+aps-point
        if abs(diff)<=1e-9:return None
        if pick.lower()=="over":return 1 if diff>0 else 0
        if pick.lower()=="under":return 1 if diff<0 else 0
    return None

def _canonical_rows(rows):
    best={}
    for r in rows:
        if r.get("record_type")=="COMBO" or r.get("result_status")!="FINAL" or not r.get("game_pk"):continue
        k=str(r.get("game_pk")); rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    return [x[1] for x in sorted(best.values(),key=lambda z:z[0])]

def _examples(rows,market):
    out=[]
    for row in _canonical_rows(rows):
        items=row.get("v11_market_challengers") or {}
        for item in items.values():
            if str(item.get("market") or "").upper()!=market:continue
            y=_market_target(row,item)
            if y is None:continue
            out.append({"date":str(row.get("game_date") or row.get("target_date") or row.get("analyzed_at") or ""),"base":clamp(item.get("base_v10_probability",.5)),"feature":_num(item.get("oriented_feature"),0),"y":y})
    out.sort(key=lambda x:x["date"]);return out

def _fit_offset(rows,l2=3.333,steps=400,lr=.03):
    a=b=0.0
    if not rows:return a,b
    scale=max(1.0,math.sqrt(sum(x["feature"]**2 for x in rows)/len(rows)))
    for step in range(steps):
        ga=gb=0.0
        for x in rows:
            f=x["feature"]/scale; q=sigmoid(logit(x["base"])+a+b*f); e=q-x["y"]; ga+=e; gb+=e*f
        ga=ga/len(rows)+l2*a/len(rows); gb=gb/len(rows)+l2*b/len(rows); eta=lr*(1-step/(steps*1.5)); a-=eta*ga; b-=eta*gb
    return a,b/scale

def evaluate_market(rows,market):
    ex=_examples(rows,market); n=len(ex)
    if n<40:return {"market":market,"n":n,"status":"COLLECTING","passes_historical":False,"candidate_params":None,"production_ready":False}
    cut=max(30,int(n*.75)); train=ex[:cut]; hold=ex[cut:]; a,b=_fit_offset(train)
    base=[x["base"] for x in hold]; chal=[sigmoid(logit(x["base"])+a+b*x["feature"]) for x in hold]; ys=[x["y"] for x in hold]
    rep=evaluate_probability_challenger(base,chal,ys); rep.update({"market":market,"train_n":len(train),"holdout_n":len(hold),"candidate_params":{"intercept":a,"oriented_feature_coef":b},"status":"PASS_HISTORICAL" if rep.get("passes") else "FAIL_HISTORICAL","passes_historical":bool(rep.get("passes")),"production_ready":production_gate(rep,0)})
    return rep

def evaluate_sharp(rows):
    xs=[]
    for r in _canonical_rows(rows):
        fs=r.get("v11_feature_snapshot") or {}; p=fs.get("market_home_probability")
        if p is None:continue
        y=1 if str(r.get("winner"))==str(r.get("home")) else 0
        xs.append((clamp(r.get("base_v10_p_home",.5)),clamp(r.get("v11_2_p_home",.5)),clamp(p),y))
    if not xs:return {"n":0,"status":"COLLECTING"}
    p10=[x[0] for x in xs]; p112=[x[1] for x in xs]; sharp=[x[2] for x in xs]; ys=[x[3] for x in xs]
    def acc(ps):return sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/len(ys)
    return {"n":len(xs),"status":"BENCHMARK_ONLY","v10":{"accuracy":acc(p10),"brier":brier(p10,ys),"logloss":logloss(p10,ys)},"v11_2":{"accuracy":acc(p112),"brier":brier(p112,ys),"logloss":logloss(p112,ys)},"sharp":{"accuracy":acc(sharp),"brier":brier(sharp,ys),"logloss":logloss(sharp,ys)},"note":"Sharp remains benchmark-only; no automatic blend or predictive-truth promotion."}

def evaluate_all(rows):
    return {"RUNLINE":evaluate_market(rows,"RUNLINE"),"TOTAL":evaluate_market(rows,"TOTAL"),"SHARP_ML_BENCHMARK":evaluate_sharp(rows)}
