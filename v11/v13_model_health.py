from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import v13_daily_tracking as tracking
from . import v13_rich_native_train as rich_native
from . import v137_free_data_health as free_data_health
from . import v138_model_health_bridge as v138_health
from .probability_contract_v13 import MODEL_GENERATION_FINGERPRINT

OUT=Path("data/v13_model_health.json")
SCHEMA="v13-model-health-v3"


def _load(path: str):
    p=Path(path)
    if not p.exists():return {}
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return {}


def _num(v: Any,d: float=0.0) -> float:
    try:
        x=float(v);return x if math.isfinite(x) else d
    except Exception:return d


def _probability_drift(states):
    rows=[s for s in states if s.get("settled_result") in {"WIN","LOSS"} and s.get("p_model") is not None]
    rows.sort(key=lambda s:str(s.get("observation_at") or s.get("observed_at") or ""))
    out={}
    for market in ("ML","RUNLINE","TOTAL"):
        xs=[_num(s.get("p_model"),.5) for s in rows if str(s.get("market") or "").upper()==market]
        recent=xs[-50:];prior=xs[-100:-50]
        out[market]={"observations":len(xs),"recent_n":len(recent),"prior_n":len(prior),
                     "recent_mean_probability":sum(recent)/len(recent) if recent else None,
                     "prior_mean_probability":sum(prior)/len(prior) if prior else None,
                     "mean_probability_shift":(sum(recent)/len(recent)-sum(prior)/len(prior)) if recent and prior else None}
    return out


def build() -> dict[str,Any]:
    cal=calibration.load_model();rich=_load("data/v13_rich_native_candidate.json") or rich_native.build()
    diag=_load("data/v13_probability_diagnostics.json");coverage=_load("data/v13_coverage_report.json")
    posterior=_load("data/v13_posterior_policy.json")
    free_data=free_data_health.build();closure_health=v138_health.build()
    states=list(tracking.fold().values())
    calibrators=cal.get("calibrators") or {}
    calibration_status={key:{"active":bool(v.get("active")),"method":v.get("method"),"n":int(v.get("n") or 0),
                             "status":v.get("status"),"strict_required_n":v.get("strict_required_n")}
                        for key,v in calibrators.items() if key=="GLOBAL" or key.startswith("MARKET:") or key.startswith("PHASE:FINAL:")}
    alerts=[]
    if int(rich.get("native_games") or 0)==0:alerts.append("rich_native_games_zero")
    if coverage and not coverage.get("complete_future_coverage",True):alerts.append("daily_future_coverage_incomplete")
    for market,m in (diag.get("by_market") or {}).items():
        if int(m.get("n") or 0)>=30 and _num(m.get("brier_gain_vs_market"),0)<0:alerts.append(f"{market.lower()}_brier_worse_than_market")
        if int(m.get("n") or 0)>=30 and m.get("gap_residual_slope") is not None and _num(m.get("gap_residual_slope"))<=0:alerts.append(f"{market.lower()}_model_market_gap_not_informative")
    for alert in free_data.get("alerts") or []:alerts.append(f"free_data:{alert}")
    for alert in closure_health.get("alerts") or []:alerts.append(f"v138:{alert}")
    return {"schema":SCHEMA,"model_generation":MODEL_GENERATION_FINGERPRINT,
            "calibration":calibration_status,
            "rich_native":{"status":rich.get("status"),"native_games":rich.get("native_games"),"minimum_games":rich.get("minimum_games"),
                           "feature_coverage":rich.get("native_feature_coverage"),"rejection_reasons":rich.get("native_rejection_reasons"),
                           "active_for_production":bool(rich.get("active_for_production"))},
            "posterior":{"historical_observations":posterior.get("historical_observations"),"live_observations":posterior.get("live_observations"),
                         "primary_probability_affected":posterior.get("primary_probability_affected")},
            "proper_scoring_vs_market":diag.get("by_market") or {},
            "daily_coverage":{"complete_future_coverage":coverage.get("complete_future_coverage"),"status_counts":coverage.get("status_counts"),
                              "future_coverage_rate":coverage.get("future_coverage_rate")},
            "probability_drift":_probability_drift(states),"free_data_foundation":free_data,"v138_audit_research":closure_health,
            "alerts":sorted(set(alerts)),
            "claim":"monitoring artifact only; alerts indicate evidence to investigate, not automatic model retuning"}


def main():
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":main()
