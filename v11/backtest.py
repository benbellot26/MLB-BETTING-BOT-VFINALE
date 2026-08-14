from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .journal import load_rows

def _num(x,d=0.0):
    try:return float(x)
    except Exception:return d

def _canonical(rows,phase=None):
    best={}
    for r in rows:
        if r.get("bet_type")=="COMBO" or r.get("result_status")!="FINAL" or not r.get("game_pk") or not r.get("options"):continue
        if phase and str(r.get("phase") or "").upper()!=phase:continue
        k=str(r.get("game_pk"));rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    return [x[1] for x in best.values()]

def _market(rows,market):
    picks=[]
    for r in rows:
        xs=[o for o in r.get("options") or [] if o.get("market")==market and o.get("result") in {"WIN","LOSS"}]
        if xs:picks.append(max(xs,key=lambda o:_num(o.get("p_effective"),.5)))
    if not picks:return {"n":0}
    n=len(picks);wins=sum(o.get("result")=="WIN" for o in picks);br=sum(_num(o.get("brier")) for o in picks)/n;ll=sum(_num(o.get("logloss")) for o in picks)/n
    sharp=[o for o in picks if o.get("sharp_brier") is not None]
    return {"n":n,"wins":wins,"accuracy":wins/n,"brier":br,"logloss":ll,"sharp_brier":sum(_num(o.get("sharp_brier")) for o in sharp)/len(sharp) if sharp else None,"sharp_logloss":sum(_num(o.get("sharp_logloss")) for o in sharp)/len(sharp) if sharp else None}

def build_report(rows=None):
    rows=load_rows() if rows is None else rows;out={}
    for phase in ("EARLY","LATE","FINAL"):
        xs=_canonical(rows,phase);out[phase]={"games":len(xs),"markets":{m:_market(xs,m) for m in ("ML","RUNLINE","TOTAL")}}
    all_rows=_canonical(rows)
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"engine":"V11 standalone all markets","methodology":{"point_in_time_only":True,"phase_separated":True,"historical_odds_fabricated":False,"v10_used_for_predictions":False},"all":{"games":len(all_rows),"markets":{m:_market(all_rows,m) for m in ("ML","RUNLINE","TOTAL")}},"phases":out}

def write_report(path="data/v11_point_in_time_backtest.json"):
    rep=build_report();p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(rep,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8");return rep

if __name__=="__main__":
    print(json.dumps(write_report(),ensure_ascii=False,indent=2,sort_keys=True))
