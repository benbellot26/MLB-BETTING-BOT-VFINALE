from __future__ import annotations

"""Append-only preregistration for Pulsar challenger experiments.

A challenger must be registered before prospective observations can count toward
promotion evidence. Editing an existing hypothesis after seeing its cohort is
represented as a NEW experiment id, never an in-place mutation.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

REGISTRY = Path("data/v14_experiment_registry.jsonl")
SCHEMA = "pulsar-v14-experiment-registry-v1"
REQUIRED = (
    "experiment_id",
    "hypothesis",
    "model",
    "features",
    "training_period",
    "validation_period",
    "primary_metric",
    "success_rule",
    "code_commit_sha",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path | str = REGISTRY) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists(): return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row = json.loads(line)
        except Exception: continue
        if isinstance(row, dict) and row.get("schema") == SCHEMA: out.append(row)
    return out


def _append(row: dict[str, Any], path: Path | str = REGISTRY) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def latest(path: Path | str = REGISTRY) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for event in _read(path):
        experiment_id = str(event.get("experiment_id") or "")
        if experiment_id: state[experiment_id] = event
    return state


def registrations(path: Path | str = REGISTRY) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for event in _read(path):
        if event.get("event") != "REGISTERED": continue
        experiment_id = str(event.get("experiment_id") or "")
        if experiment_id and experiment_id not in out: out[experiment_id] = event
    return out


def register(spec: dict[str, Any], path: Path | str = REGISTRY, *, registered_at: str | None = None) -> dict[str, Any]:
    missing = [key for key in REQUIRED if spec.get(key) in (None, "", [])]
    if missing: raise ValueError(f"experiment spec missing required fields: {missing}")
    experiment_id = str(spec["experiment_id"]).strip()
    if experiment_id in registrations(path): raise ValueError("experiment_id already registered; changed hypotheses require a new id")
    row = {
        "schema": SCHEMA, "event": "REGISTERED", "status": "SEALED_PROSPECTIVE",
        "registered_at": registered_at or _now(), "experiment_id": experiment_id,
        "hypothesis": str(spec["hypothesis"]), "model": str(spec["model"]), "features": list(spec["features"]),
        "training_period": str(spec["training_period"]), "validation_period": str(spec["validation_period"]),
        "primary_metric": str(spec["primary_metric"]), "secondary_metrics": list(spec.get("secondary_metrics") or []),
        "success_rule": str(spec["success_rule"]), "code_commit_sha": str(spec["code_commit_sha"]),
        "multiplicity_family": str(spec.get("multiplicity_family") or experiment_id),
        "prospective_only_for_promotion": True, "historical_2026_role": "ROLLING_AUDIT_NOT_BLIND_HOLDOUT",
        "auto_activation": False,
    }
    _append(row, path); return row


def bootstrap_specs(spec_path: Path | str, path: Path | str = REGISTRY, *, commit_sha: str | None = None) -> dict[str, Any]:
    raw=json.loads(Path(spec_path).read_text(encoding="utf-8")); specs=raw if isinstance(raw,list) else raw.get("experiments") or []
    existing=registrations(path); created=[]; sha=commit_sha or os.getenv("GITHUB_SHA") or "LOCAL_UNRESOLVED_SHA"
    for raw_spec in specs:
        if not isinstance(raw_spec,dict): continue
        experiment_id=str(raw_spec.get("experiment_id") or "")
        if not experiment_id or experiment_id in existing: continue
        spec=dict(raw_spec)
        if str(spec.get("code_commit_sha") or "").upper() in {"AUTO","GITHUB_SHA"}: spec["code_commit_sha"]=sha
        row=register(spec,path); created.append(row["experiment_id"]); existing[row["experiment_id"]]=row
    return {"created":created,"registered_total":len(existing),"commit_sha":sha,"prospective_only":True}


def set_status(experiment_id: str, status: str, path: Path | str = REGISTRY, *, note: str | None = None) -> dict[str, Any]:
    registered = registrations(path).get(str(experiment_id))
    if not registered: raise ValueError("experiment must be registered before status transitions")
    allowed = {"COLLECTING", "REJECTED", "PROMOTION_CANDIDATE", "ARCHIVED"}; normalized = str(status).upper()
    if normalized not in allowed: raise ValueError(f"unsupported status: {normalized}")
    row = {"schema": SCHEMA, "event": "STATUS", "experiment_id": str(experiment_id), "status": normalized,
           "recorded_at": _now(), "registration_timestamp": registered.get("registered_at"),
           "primary_metric": registered.get("primary_metric"), "success_rule": registered.get("success_rule"),
           "note": note, "auto_activation": False}
    _append(row, path); return row


def eligible_observation(experiment_id: str, observed_at: str, path: Path | str = REGISTRY) -> bool:
    row = registrations(path).get(str(experiment_id))
    if not row: return False
    try:
        registered = datetime.fromisoformat(str(row["registered_at"]).replace("Z", "+00:00")); observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        if registered.tzinfo is None: registered = registered.replace(tzinfo=timezone.utc)
        if observed.tzinfo is None: observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(timezone.utc) >= registered.astimezone(timezone.utc)
    except Exception: return False


def verify(path: Path | str = REGISTRY) -> dict[str, Any]:
    events = _read(path); regs = registrations(path); failures: list[str] = []; seen: set[str] = set()
    for event in events:
        experiment_id = str(event.get("experiment_id") or "")
        if event.get("event") == "REGISTERED":
            if experiment_id in seen: failures.append(f"duplicate_registration:{experiment_id}")
            seen.add(experiment_id)
        elif experiment_id not in regs: failures.append(f"status_without_registration:{experiment_id}")
    return {"schema": "pulsar-v14-experiment-registry-audit-v1", "valid": not failures, "events": len(events), "experiments": len(regs), "failures": failures,
            "policy": "append-only preregistration; changed hypothesis => new experiment id; only post-registration observations may promote"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Pulsar append-only research experiment registry"); sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("register"); r.add_argument("--spec", required=True); r.add_argument("--registry", default=str(REGISTRY))
    b = sub.add_parser("bootstrap"); b.add_argument("--specs", required=True); b.add_argument("--registry", default=str(REGISTRY)); b.add_argument("--commit-sha")
    s = sub.add_parser("status"); s.add_argument("experiment_id"); s.add_argument("status"); s.add_argument("--note"); s.add_argument("--registry", default=str(REGISTRY))
    v = sub.add_parser("verify"); v.add_argument("--registry", default=str(REGISTRY))
    args = parser.parse_args()
    if args.command == "register": out = register(json.loads(Path(args.spec).read_text(encoding="utf-8")), args.registry)
    elif args.command == "bootstrap": out = bootstrap_specs(args.specs,args.registry,commit_sha=args.commit_sha)
    elif args.command == "status": out = set_status(args.experiment_id,args.status,args.registry,note=args.note)
    else: out = verify(args.registry)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__": main()
