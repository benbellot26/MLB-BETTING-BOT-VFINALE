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
SCHEMA="v13-model-health-v4"
EDGE_EVIDENCE_MIN=300


def _load(path: str):
    p=Path(path)
    if not p.exists():return {}
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return {}


def _num(v: Any,d: float=0.0) -> float:
    try:
        x=float(v);return x if math.isfinite(x) else d
    except Exception:return d


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _canonical_probability_state(state: dict[str,Any]) -> bool:
    market=str(state.get("market") or "").upper();pick=str(state.get("pick") or "");home=str(state.get("home") or "")
    if market=="ML":return _norm(pick)==_norm(home)
    if market=="RUNLINE":return bool(state.get("canonical")) and _norm(pick)==_norm(home)
    if market=="TOTAL":return bool(state.get("canonical")) and pick.lower()=="over"
    return False


def _probability_drift(states):
    """Monitor directional/certainty drift on one canonical side per market.

    Averaging both complementary sides mechanically converges to 0.50 and can
    hide major changes. Canonical-side probability and absolute distance from
    50% remain informative even when probabilities are perfectly complementary.
    """
    rows=[s for s in states if s.get("settled_result") in {"WIN","LOSS"}
          and s.get("p_model") is not None and _canonical_probability_state(s)]
    rows.sort(key=lambda s:str(s.get("observation_at") or s.get("observed_at") or ""))
    out={}
    for market in ("ML","RUNLINE","TOTAL"):
        xs=[_num(s.get("p_model"),.5) for s in rows if str(s.get("market") or "").upper()==market]
        recent=xs[-50:];prior=xs[-100:-50]
        recent_conf=[abs(x-.5) for x in recent];prior_conf=[abs(x-.5) for x in prior]
        recent_mean=sum(recent)/len(recent) if recent else None
        prior_mean=sum(prior)/len(prior) if prior else None
        recent_conf_mean=sum(recent_conf)/len(recent_conf) if recent_conf else None
        prior_conf_mean=sum(prior_conf)/len(prior_conf) if prior_conf else None
        out[market]={"observations":len(xs),"recent_n":len(recent),"prior_n":len(prior),
                     "recent_mean_probability":recent_mean,
                     "prior_mean_probability":prior_mean,
                     "mean_probability_shift":recent_mean-prior_mean if recent_mean is not None and prior_mean is not None else None,
                     "recent_mean_abs_edge_from_50":recent_conf_mean,
                     "prior_mean_abs_edge_from_50":prior_conf_mean,
                     "confidence_shift":recent_conf_mean-prior_conf_mean if recent_conf_mean is not None and prior_conf_mean is not None else None,
                     "sample_policy":"one canonical settled side per game/market"}
    return out


def _edge_evidence(diag: dict[str,Any]) -> dict[str,Any]:
    out={}
    for market in ("ML","RUNLINE","TOTAL"):
        metrics=(diag.get("by_market") or {}).get(market) or {}
        n=int(metrics.get("n") or 0)
        brier=_num(metrics.get("brier_gain_vs_market"),-999)
        logloss=_num(metrics.get("logloss_gain_vs_market"),-999)
        slope=metrics.get("gap_residual_slope")
        allowed=bool(n>=EDGE_EVIDENCE_MIN and brier>0 and logloss>=0 and slope is not None and _num(slope)>0)
        if n<EDGE_EVIDENCE_MIN:reason="INSUFFICIENT_INDEPENDENT_MARKET_TARGETS"
        elif brier<=0 or logloss<0:reason="MODEL_NOT_BETTER_THAN_MARKET_ON_PROPER_SCORE"
        elif slope is None or _num(slope)<=0:reason="MODEL_MARKET_GAP_NOT_INFORMATIVE"
        else:reason="PASS"
        out[market]={"claim_allowed":allowed,"n":n,"minimum_n":EDGE_EVIDENCE_MIN,"reason":reason,
                     "brier_gain_vs_market":metrics.get("brier_gain_vs_market"),
                     "logloss_gain_vs_market":metrics.get("logloss_gain_vs_market"),
                     "gap_residual_slope":slope}
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
    edge_evidence=_edge_evidence(diag)
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
            "edge_evidence":edge_evidence,
            "any_market_edge_claim_allowed":any(v.get("claim_allowed") for v in edge_evidence.values()),
            "daily_coverage":{"complete_future_coverage":coverage.get("complete_future_coverage"),"status_counts":coverage.get("status_counts"),
                              "future_coverage_rate":coverage.get("future_coverage_rate")},
            "probability_drift":_probability_drift(states),"free_data_foundation":free_data,"v138_audit_research":closure_health,
            "alerts":sorted(set(alerts)),
            "claim":"monitoring artifact only; market-edge claims are blocked until each market independently clears proper-score and sample-size evidence"}


def main():
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":main()
