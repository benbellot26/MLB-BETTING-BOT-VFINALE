from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from . import config, pro_model, storage
from .journal import load_rows


def _num(x, d=0.0):
    try:return float(x)
    except Exception:return d

def _dt(s):
    try:return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:return None


def _canonical(rows, phase=None):
    best={}
    for r in rows:
        if r.get("bet_type")=="COMBO" or r.get("result_status")!="FINAL" or not r.get("game_pk") or not r.get("options"):continue
        if phase and str(r.get("phase") or "").upper()!=phase:continue
        analyzed,game_time=_dt(r.get("analyzed_at")),_dt(r.get("game_date"))
        if analyzed and game_time and analyzed>=game_time:continue
        k=str(r.get("game_pk")); rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    return [x[1] for x in best.values()]


def _binary_metrics(ps,ys):
    if not ps:return {"n":0}
    n=len(ps)
    return {"n":n,"accuracy":sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n,
            "brier":sum((p-y)**2 for p,y in zip(ps,ys))/n,
            "logloss":sum(-(y*math.log(max(.001,min(.999,p)))+(1-y)*math.log(max(.001,min(.999,1-p)))) for p,y in zip(ps,ys))/n}


def _market(rows,market):
    chosen=[]
    for r in rows:
        xs=[o for o in r.get("options") or [] if o.get("market")==market and o.get("result") in {"WIN","LOSS"}]
        if xs:chosen.append(max(xs,key=lambda o:_num(o.get("p_effective"),.5)))
    if not chosen:return {"n":0}
    ys=[1 if o.get("result")=="WIN" else 0 for o in chosen]; model=[_num(o.get("p_effective"),.5) for o in chosen]; structural=[_num(o.get("p_structural"),.5) for o in chosen]
    sharp=[(o.get("p_market"),y) for o,y in zip(chosen,ys) if o.get("p_market") is not None]
    out={"n":len(chosen),"model":_binary_metrics(model,ys),"structural":_binary_metrics(structural,ys),"sharp":_binary_metrics([_num(p,.5) for p,_ in sharp],[y for _,y in sharp]),"calibration_bins":[]}
    for lo in (.50,.55,.60,.65,.70,.75):
        hi=1.01 if lo==.75 else lo+.05; z=[(p,y) for p,y in zip(model,ys) if lo<=p<hi]
        if z:out["calibration_bins"].append({"bin":f"{int(lo*100)}-{100 if hi>1 else int(hi*100)}%","n":len(z),"avg_probability":sum(p for p,_ in z)/len(z),"hit_rate":sum(y for _,y in z)/len(z)})
    return out


def _walk_forward(rows,step=50):
    ordered=sorted(_canonical(rows),key=lambda r:str(r.get("game_date") or r.get("analyzed_at") or "")); checks=[]
    for end in range(config.MIN_RESIDUAL_TRAIN_GAMES,len(ordered),step):
        train=ordered[:end]; c=pro_model.build_candidate(train)
        checks.append({"trained_games":end,"through":train[-1].get("game_date") if train else None,"passes":c.get("passes"),
          "residual":{k:(c.get("residual") or {}).get(k) for k in ("active","base_rmse","model_rmse","holdout_n","passes")},
          "calibration":{m:{k:(c.get("calibration",{}).get(m) or {}).get(k) for k in ("active","n","holdout_n","brier_gain","passes")} for m in ("ML","RUNLINE","TOTAL")}})
    return checks


def build_report(rows=None):
    rows=load_rows() if rows is None else rows; phases={}
    for phase in ("EARLY","LATE","FINAL"):
        xs=_canonical(rows,phase); phases[phase]={"games":len(xs),"markets":{m:_market(xs,m) for m in ("ML","RUNLINE","TOTAL")}}
    all_rows=_canonical(rows)
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"engine":config.VERSION,
      "methodology":{"point_in_time_only":True,"strictly_pregame_rows":True,"phase_separated":True,"historical_odds_fabricated":False,"walk_forward_challenger":True,
                     "claim_limit":"Full historical engine replay requires archived raw/API snapshots; absent observations are never reconstructed from future data."},
      "all":{"games":len(all_rows),"markets":{m:_market(all_rows,m) for m in ("ML","RUNLINE","TOTAL")}},"phases":phases,"walk_forward":_walk_forward(rows),"betting":storage.ledger_summary()}


def write_report(path="data/v11_point_in_time_backtest.json"):
    rep=build_report(); p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(rep,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); return rep

if __name__=="__main__":print(json.dumps(write_report(),ensure_ascii=False,indent=2,sort_keys=True))
