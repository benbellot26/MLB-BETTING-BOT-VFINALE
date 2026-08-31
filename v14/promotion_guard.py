from __future__ import annotations

"""Fail-closed promotion gate for preregistered Pulsar challengers.

Challenger research artifacts may use historical or reused evidence for ranking,
diagnostics and nomination. They may not pass a promotion-capable status through
the production research workflow unless the artifact explicitly proves that the
promotion decision used only the cohort sealed after preregistration.

This module does not score a challenger and never activates one. It is a final
scientific governance gate between research outputs and persisted promotion
claims.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .research_registry import REGISTRY, registrations

OUTPUT=Path("data/v14_promotion_guard.json")
PROMOTION_STATUSES={"PROMOTION_ELIGIBLE","PROMOTION_REVIEW","PROMOTION_CANDIDATE","PROSPECTIVE_PROMOTION_ELIGIBLE"}
ARTIFACT_EXPERIMENTS={
    "data/v14_distribution_candidate.json":"V14-DISTRIBUTION-01",
    "data/v14_heteroskedastic_candidate.json":"V14-HETERO-01",
    "data/v14_learned_run_mean_candidate.json":"V14-RUNMEAN-01",
    "data/v14_residual_challenger.json":"V14-RESIDUAL-01",
    "data/v14_calibration_methods_candidate.json":"V14-CALMETHOD-01",
    "data/v14_bootstrap_uncertainty_candidate.json":"V14-UNCERTAINTY-01",
    "data/v14_sharp_book_weights_candidate.json":"V14-SHARPWEIGHT-01",
    "data/v14_market_posterior_candidate.json":"V14-MARKETPOST-01",
}


def _dt(value:Any)->datetime|None:
    try:
        out=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if out.tzinfo is None:out=out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:return None


def _load(path:Path|str)->dict[str,Any]:
    target=Path(path)
    if not target.exists():return {}
    try:value=json.loads(target.read_text(encoding="utf-8"))
    except Exception:return {}
    return value if isinstance(value,dict) else {}


def _promotion_paths(value:Any,path:str="root")->list[tuple[str,str]]:
    found=[]
    if isinstance(value,dict):
        status=str(value.get("status") or "").upper()
        if status in PROMOTION_STATUSES:found.append((path,status))
        for key,child in value.items():
            if isinstance(child,(dict,list)):found.extend(_promotion_paths(child,f"{path}.{key}"))
    elif isinstance(value,list):
        for index,child in enumerate(value):
            if isinstance(child,(dict,list)):found.extend(_promotion_paths(child,f"{path}[{index}]"))
    return found


def _evidence_ok(artifact:dict[str,Any],registration:dict[str,Any])->tuple[bool,list[str]]:
    evidence=artifact.get("promotion_evidence") or {}; failures=[]
    if evidence.get("prospective_only") is not True:failures.append("prospective_only_evidence_required")
    if str(evidence.get("experiment_id") or "")!=str(registration.get("experiment_id") or ""):failures.append("experiment_id_mismatch")
    registered_at=_dt(registration.get("registered_at")); evidence_registered=_dt(evidence.get("registration_timestamp")); first=_dt(evidence.get("first_observation_at")); latest=_dt(evidence.get("latest_observation_at"))
    if registered_at is None:failures.append("registration_timestamp_invalid")
    if evidence_registered is None or registered_at is None or evidence_registered!=registered_at:failures.append("evidence_registration_timestamp_mismatch")
    if first is None:failures.append("prospective_first_observation_missing")
    elif registered_at is not None and first<registered_at:failures.append("pre_registration_observation_in_promotion_evidence")
    if latest is None:failures.append("prospective_latest_observation_missing")
    elif first is not None and latest<first:failures.append("prospective_observation_order_invalid")
    try:eligible=int(evidence.get("eligible_observations") or 0)
    except Exception:eligible=0
    if eligible<=0:failures.append("prospective_eligible_observations_missing")
    registered_sha=str(registration.get("code_commit_sha") or ""); evidence_sha=str(evidence.get("code_commit_sha") or "")
    if not registered_sha or registered_sha.upper() in {"AUTO","GITHUB_SHA","LOCAL_UNRESOLVED_SHA"}:failures.append("registered_code_sha_unresolved")
    if evidence_sha!=registered_sha:failures.append("promotion_code_sha_mismatch")
    if evidence.get("success_rule_locked") is not True:failures.append("locked_success_rule_required")
    return not failures,failures


def build(*,registry:Path|str=REGISTRY,artifact_paths:dict[str,str]|None=None)->dict[str,Any]:
    regs=registrations(registry); mapping=artifact_paths or ARTIFACT_EXPERIMENTS; artifacts={}; unsafe=[]
    for raw_path,experiment_id in mapping.items():
        artifact=_load(raw_path); promotion_paths=_promotion_paths(artifact); registration=regs.get(experiment_id); failures=[]; authorized=False
        if not artifact:failures.append("artifact_missing")
        if registration is None:failures.append("experiment_not_preregistered")
        if promotion_paths:
            if registration is not None:
                authorized,evidence_failures=_evidence_ok(artifact,registration); failures.extend(evidence_failures)
            if not authorized:
                unsafe.append({"artifact":raw_path,"experiment_id":experiment_id,"promotion_paths":promotion_paths,"failures":sorted(set(failures))})
        artifacts[raw_path]={"experiment_id":experiment_id,"registered":registration is not None,"registered_at":registration.get("registered_at") if registration else None,"registered_code_commit_sha":registration.get("code_commit_sha") if registration else None,"promotion_claims":[{"path":p,"status":s} for p,s in promotion_paths],"promotion_authorized":bool(promotion_paths and authorized),"failures":sorted(set(failures))}
    return {"schema":"pulsar-v14-promotion-guard-v1","generated_at":datetime.now(timezone.utc).isoformat(),"fail_closed":True,"promotion_statuses":sorted(PROMOTION_STATUSES),"unsafe_promotion_claims":unsafe,"valid":not unsafe,"policy":"historical/reused evidence may nominate or rank challengers; persisted promotion-capable claims require exact preregistration provenance and post-registration prospective-only evidence","artifacts":artifacts}


def write(*,registry:Path|str=REGISTRY,output:Path|str=OUTPUT,fail_on_unsafe:bool=False)->dict[str,Any]:
    out=build(registry=registry); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if fail_on_unsafe and not out["valid"]:raise SystemExit("unsafe challenger promotion claim blocked by preregistration guard")
    return out


def main()->None:
    parser=argparse.ArgumentParser(description="Fail-closed preregistered challenger promotion guard");parser.add_argument("--registry",default=str(REGISTRY));parser.add_argument("--output",default=str(OUTPUT));parser.add_argument("--fail-on-unsafe",action="store_true");args=parser.parse_args();out=write(registry=args.registry,output=args.output,fail_on_unsafe=args.fail_on_unsafe);print(json.dumps({"valid":out["valid"],"unsafe":len(out["unsafe_promotion_claims"])},sort_keys=True))


if __name__=="__main__":main()
