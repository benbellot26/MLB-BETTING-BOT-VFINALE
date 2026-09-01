from __future__ import annotations

"""Zero-network operational/data-quality dashboard for Pulsar V14.

The dashboard intentionally separates *operational data health* from *betting
certification*. A healthy pipeline can still be RESEARCH_ONLY, and an old/stale
certification artifact is surfaced as an identity warning instead of being
silently interpreted as current evidence.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID, VERSION
from .feature_ownership import contract_payload

DEFAULT_OUTPUT=Path("data/v14_data_quality_dashboard.json")


def _load(path:Path|str)->dict[str,Any]:
    p=Path(path)
    if not p.exists():return {}
    try:value=json.loads(p.read_text(encoding="utf-8"))
    except Exception:return {}
    return value if isinstance(value,dict) else {}


def _ratio(used:Any,limit:Any)->float|None:
    try:u=float(used);l=float(limit)
    except Exception:return None
    return u/l if l>0 else None


def build(*,root:Path|str=".",now:datetime|None=None)->dict[str,Any]:
    base=Path(root);current=now or datetime.now(timezone.utc)
    coverage=_load(base/"data/v14_coverage_report.json");cert=_load(base/"data/v14_betting_certification.json");api=_load(base/"data/v14_api_usage_report.json");statcast=_load(base/"data/v14_statcast_priors_report.json");defense=_load(base/"data/v14_defense_baserunning_priors.json")
    unique=((coverage.get("scheduled_final_trigger") or {}).get("first_observation_unique_games") or {})
    all_paid=api.get("all_paid_month") or {};auto=api.get("automated_month") or {}
    all_ratio=_ratio(all_paid.get("provider_credits_used"),all_paid.get("provider_credit_limit"));auto_ratio=_ratio(auto.get("provider_credits_used"),auto.get("provider_credit_limit"))
    warnings=[];critical=[]
    if coverage and coverage.get("model_generation")!=MODEL_GENERATION:critical.append("coverage_generation_mismatch")
    if cert and cert.get("model_generation")!=MODEL_GENERATION:warnings.append("certification_generation_mismatch_pending_zero_api_reset")
    if statcast and statcast.get("point_in_time") is not True:critical.append("statcast_not_point_in_time")
    if statcast and statcast.get("stable_id_only") is not True:critical.append("statcast_not_stable_id_only")
    if all_ratio is not None and all_ratio>=.90:critical.append("odds_all_paid_budget_above_90pct")
    elif all_ratio is not None and all_ratio>=.75:warnings.append("odds_all_paid_budget_above_75pct")
    scheduled_n=int(unique.get("observations") or unique.get("predicted") or 0)
    if scheduled_n<30:warnings.append("current_generation_scheduled_final_sample_very_small")
    operational="RED" if critical else ("AMBER" if warnings else "GREEN")
    return {
        "schema":"pulsar-v14-data-quality-dashboard-v1",
        "generated_at":current.astimezone(timezone.utc).isoformat(),
        "network_calls":0,
        "software_version":VERSION,
        "model_generation":MODEL_GENERATION,
        "probability_policy_id":PROBABILITY_POLICY_ID,
        "operational_status":operational,
        "betting_status":cert.get("betting_status") or "RESEARCH_ONLY",
        "betting_certified":cert.get("certified") is True and cert.get("model_generation")==MODEL_GENERATION,
        "current_generation_scheduled_final_unique_games":scheduled_n,
        "coverage":{"eligible_coverage":unique.get("eligible_coverage"),"market_fresh_coverage":unique.get("market_fresh_coverage"),"sharp_coverage":unique.get("sharp_coverage"),"execution_coverage":unique.get("execution_coverage")},
        "api_budget":{"all_paid":all_paid,"automated":auto,"all_paid_fraction_used":all_ratio,"automated_fraction_used":auto_ratio},
        "statcast":{"schema":statcast.get("schema"),"cutoff_day":statcast.get("cutoff_day"),"lookback_days":statcast.get("lookback_days"),"point_in_time":statcast.get("point_in_time"),"stable_id_only":statcast.get("stable_id_only"),"coverage":statcast.get("coverage") or {}},
        "defense_catcher_baserunning":{"schema":defense.get("schema"),"cutoff_day":defense.get("cutoff_day"),"coverage":defense.get("coverage") or {},"point_in_time":defense.get("point_in_time")},
        "feature_ownership":contract_payload(),
        "warnings":warnings,
        "critical":critical,
        "interpretation":"operational_status measures evidence/data plumbing only; it never authorizes betting",
    }


def write(*,root:Path|str=".",output:Path|str=DEFAULT_OUTPUT)->dict[str,Any]:
    out=build(root=root);p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return out


def main()->None:
    parser=argparse.ArgumentParser(description="Build zero-API Pulsar V14 data quality dashboard");parser.add_argument("--root",default=".");parser.add_argument("--output",default=str(DEFAULT_OUTPUT));args=parser.parse_args();print(json.dumps(write(root=args.root,output=args.output),ensure_ascii=False,sort_keys=True))

if __name__=="__main__":main()
