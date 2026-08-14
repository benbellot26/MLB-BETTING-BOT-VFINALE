from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .journal import load_rows
from .champion import evaluate_all

def _canonical_phase(rows, phase):
    best={}
    for r in rows:
        if r.get("record_type")=="COMBO" or r.get("result_status")!="FINAL" or str(r.get("phase") or "").upper()!=phase or not r.get("game_pk"):continue
        k=str(r.get("game_pk")); rank=str(r.get("analyzed_at") or "")
        if k not in best or rank>best[k][0]:best[k]=(rank,r)
    return [x[1] for x in best.values()]

def _phase_metrics(rows,phase):
    xs=_canonical_phase(rows,phase); n=len(xs)
    if not n:return {"n":0}
    w10=sum(bool(x.get("v10_correct")) for x in xs); w11=sum(bool(x.get("v11_3_correct")) for x in xs)
    b10=[float(x["v10_brier"]) for x in xs if x.get("v10_brier") is not None]; b112=[float(x["v11_2_brier"]) for x in xs if x.get("v11_2_brier") is not None]
    return {"n":n,"v10_accuracy":w10/n,"v11_3_accuracy":w11/n,"v10_brier":sum(b10)/len(b10) if b10 else None,"v11_2_brier":sum(b112)/len(b112) if b112 else None}

def build_report(rows=None):
    rows=load_rows() if rows is None else rows
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"methodology":{"point_in_time_only":True,"historical_odds_fabricated":False,"phase_separated":True,"note":"Only snapshots actually captured before games are graded; no final lineup is injected into EARLY/LATE."},"phases":{p:_phase_metrics(rows,p) for p in ("EARLY","LATE","FINAL")},"challengers":evaluate_all(rows)}

def write_report(path="data/v11_point_in_time_backtest.json"):
    rep=build_report(); p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(rep,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); return rep
