from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from .journal import load_rows

def _num(x,d=0.0):
    try:return float(x)
    except Exception:return d
def _logit(p):
    p=max(.001,min(.999,p));return math.log(p/(1-p))
def _sigmoid(z):return 1/(1+math.exp(-max(-30,min(30,z))))

def _examples(rows,market):
    best={}
    for r in rows:
        if r.get("result_status")!="FINAL" or not r.get("game_pk") or not r.get("options"):continue
        k=str(r.get("game_pk"));rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    out=[]
    for _,r in sorted(best.values(),key=lambda z:z[0]):
        xs=[o for o in r.get("options") or [] if o.get("market")==market and o.get("result") in {"WIN","LOSS"}]
        if not xs:continue
        o=max(xs,key=lambda x:_num(x.get("p_effective"),.5));out.append((_num(o.get("p_effective"),.5),1 if o.get("result")=="WIN" else 0))
    return out

def _metrics(ps,ys):
    if not ps:return {"n":0}
    b=sum((p-y)**2 for p,y in zip(ps,ys))/len(ps);ll=sum(-(y*math.log(max(.001,min(.999,p)))+(1-y)*math.log(max(.001,min(.999,1-p)))) for p,y in zip(ps,ys))/len(ps)
    return {"n":len(ps),"brier":b,"logloss":ll,"accuracy":sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/len(ps)}

def _fit_intercept(train):
    best=(0.0,1e9)
    for i in range(-60,61):
        a=i/200
        ps=[_sigmoid(_logit(p)+a) for p,_ in train];ys=[y for _,y in train];b=_metrics(ps,ys)["brier"]
        if b<best[1]:best=(a,b)
    return best[0]

def build_candidate(rows=None):
    rows=load_rows() if rows is None else rows;markets={}
    for market in ("ML","RUNLINE","TOTAL"):
        ex=_examples(rows,market);n=len(ex)
        if n<80:
            markets[market]={"n":n,"status":"COLLECTING","active":False};continue
        cut=max(60,int(n*.75));train,hold=ex[:cut],ex[cut:];a=_fit_intercept(train);base=[p for p,_ in hold];ys=[y for _,y in hold];cand=[_sigmoid(_logit(p)+a) for p in base];mb=_metrics(base,ys);mc=_metrics(cand,ys);gain=mb["brier"]-mc["brier"]
        markets[market]={"n":n,"train_n":len(train),"holdout_n":len(hold),"intercept":a,"base":mb,"candidate":mc,"brier_gain":gain,"passes":len(hold)>=30 and gain>=.0015 and mc["logloss"]<=mb["logloss"],"active":False}
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"engine":"V11 standalone","official_effect":False,"auto_promotion":False,"markets":markets}

def write_candidate(path="data/v11_candidate_model.json"):
    c=build_candidate();p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(c,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8");return c

if __name__=="__main__":
    print(json.dumps(write_candidate(),ensure_ascii=False,indent=2,sort_keys=True))
