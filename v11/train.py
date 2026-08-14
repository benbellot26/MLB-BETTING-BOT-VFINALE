from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .champion import evaluate_market
from .journal import load_rows
from .models import load_model

def build_candidate(rows=None):
    rows = load_rows() if rows is None else rows
    base = load_model(); reports = {m:evaluate_market(rows,m) for m in ("RUNLINE","TOTAL")}
    candidate = {"generated_at":datetime.now(timezone.utc).isoformat(),"official_effect":False,"auto_promotion":False,"base_model_version":base.get("version"),"challengers":{},"evidence":reports}
    for market, rep in reports.items():
        params = rep.get("candidate_params")
        if not params: continue
        if market == "RUNLINE": cfg={"active":False,"intercept":params["intercept"],"oriented_run_diff_coef":params["oriented_feature_coef"]}
        else: cfg={"active":False,"intercept":params["intercept"],"oriented_total_residual_coef":params["oriented_feature_coef"]}
        candidate["challengers"][market]=cfg
    return candidate

def write_candidate(path="data/v11_candidate_model.json"):
    candidate=build_candidate(); p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(candidate,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); return candidate
