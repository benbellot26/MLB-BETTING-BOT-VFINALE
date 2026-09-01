from __future__ import annotations

"""Append-only preregistration for Pulsar challenger experiments.

A challenger must be registered before prospective observations can count toward
promotion evidence. Editing an existing hypothesis after seeing its cohort is
represented as a NEW experiment id, never an in-place mutation.

New registrations use the stricter governance contract introduced after V14.6:
minimum independent sample, analysis plan, stopping rule and promotion scope are
sealed in addition to the original hypothesis/metric/success rule. Historical
v1 registrations remain readable and auditable but are never silently rewritten.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

REGISTRY = Path("data/v14_experiment_registry.jsonl")
SCHEMA = "pulsar-v14-experiment-registry-v1"
GOVERNANCE_POLICY = "pulsar-v14-research-governance-v2"
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
STRICT_REQUIRED = (
    "minimum_independent_games",
    "analysis_plan",
    "stopping_rule",
    "promotion_scope",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path | str = REGISTRY) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("schema") == SCHEMA:
            out.append(row)
    return out


def _append(row: dict[str, Any], path: Path | str = REGISTRY) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def latest(path: Path | str = REGISTRY) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for event in _read(path):
        experiment_id = str(event.get("experiment_id") or "")
        if experiment_id:
            state[experiment_id] = event
    return state


def registrations(path: Path | str = REGISTRY) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for event in _read(path):
        if event.get("event") != "REGISTERED":
            continue
        experiment_id = str(event.get("experiment_id") or "")
        if experiment_id and experiment_id not in out:
            out[experiment_id] = event
    return out


def _immutable_spec(row: dict[str, Any]) -> dict[str, Any]:
    keys = REQUIRED + STRICT_REQUIRED + (
        "secondary_metrics",
        "multiplicity_family",
        "research_budget_family",
    )
    return {key: row.get(key) for key in keys}


def spec_fingerprint(row: dict[str, Any]) -> str:
    payload = json.dumps(_immutable_spec(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def register(
    spec: dict[str, Any],
    path: Path | str = REGISTRY,
    *,
    registered_at: str | None = None,
) -> dict[str, Any]:
    strict = str(spec.get("governance_policy") or "") == GOVERNANCE_POLICY
    required = REQUIRED + STRICT_REQUIRED if strict else REQUIRED
    missing = [key for key in required if spec.get(key) in (None, "", [])]
    if missing:
        raise ValueError(f"experiment spec missing required fields: {missing}")
    minimum_games = None
    if strict:
        try:
            minimum_games = int(spec["minimum_independent_games"])
        except Exception as exc:
            raise ValueError("minimum_independent_games must be an integer") from exc
        if minimum_games < 20:
            raise ValueError("minimum_independent_games must be >= 20 for a new predictive experiment")

    experiment_id = str(spec["experiment_id"]).strip()
    if experiment_id in registrations(path):
        raise ValueError("experiment_id already registered; changed hypotheses require a new id")

    row = {
        "schema": SCHEMA,
        "event": "REGISTERED",
        "status": "SEALED_PROSPECTIVE",
        "governance_policy": GOVERNANCE_POLICY if strict else "LEGACY_V1",
        "registered_at": registered_at or _now(),
        "experiment_id": experiment_id,
        "hypothesis": str(spec["hypothesis"]),
        "model": str(spec["model"]),
        "features": list(spec["features"]),
        "training_period": str(spec["training_period"]),
        "validation_period": str(spec["validation_period"]),
        "primary_metric": str(spec["primary_metric"]),
        "secondary_metrics": list(spec.get("secondary_metrics") or []),
        "success_rule": str(spec["success_rule"]),
        "minimum_independent_games": minimum_games,
        "analysis_plan": str(spec.get("analysis_plan") or ""),
        "stopping_rule": str(spec.get("stopping_rule") or ""),
        "promotion_scope": str(spec.get("promotion_scope") or ""),
        "code_commit_sha": str(spec["code_commit_sha"]),
        "multiplicity_family": str(spec.get("multiplicity_family") or experiment_id),
        "research_budget_family": str(spec.get("research_budget_family") or spec.get("multiplicity_family") or experiment_id),
        "prospective_only_for_promotion": True,
        "historical_2026_role": "ROLLING_AUDIT_NOT_BLIND_HOLDOUT",
        "auto_activation": False,
    }
    row["spec_fingerprint"] = spec_fingerprint(row) if strict else None
    _append(row, path)
    return row


def bootstrap_specs(
    spec_path: Path | str,
    path: Path | str = REGISTRY,
    *,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    raw = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    specs = raw if isinstance(raw, list) else raw.get("experiments") or []
    existing = registrations(path)
    created = []
    sha = commit_sha or os.getenv("GITHUB_SHA") or "LOCAL_UNRESOLVED_SHA"
    for raw_spec in specs:
        if not isinstance(raw_spec, dict):
            continue
        experiment_id = str(raw_spec.get("experiment_id") or "")
        # Existing sealed experiments are deliberately not revalidated against
        # newer governance fields: changing their contract after observation
        # would itself be post-hoc research.
        if not experiment_id or experiment_id in existing:
            continue
        spec = dict(raw_spec)
        if str(spec.get("code_commit_sha") or "").upper() in {"AUTO", "GITHUB_SHA"}:
            spec["code_commit_sha"] = sha
        row = register(spec, path)
        created.append(row["experiment_id"])
        existing[row["experiment_id"]] = row
    return {
        "created": created,
        "registered_total": len(existing),
        "commit_sha": sha,
        "prospective_only": True,
        "governance_policy": GOVERNANCE_POLICY,
    }


def set_status(
    experiment_id: str,
    status: str,
    path: Path | str = REGISTRY,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    registered = registrations(path).get(str(experiment_id))
    if not registered:
        raise ValueError("experiment must be registered before status transitions")
    allowed = {"COLLECTING", "REJECTED", "PROMOTION_CANDIDATE", "ARCHIVED"}
    normalized = str(status).upper()
    if normalized not in allowed:
        raise ValueError(f"unsupported status: {normalized}")
    row = {
        "schema": SCHEMA,
        "event": "STATUS",
        "experiment_id": str(experiment_id),
        "status": normalized,
        "recorded_at": _now(),
        "registration_timestamp": registered.get("registered_at"),
        "primary_metric": registered.get("primary_metric"),
        "success_rule": registered.get("success_rule"),
        "minimum_independent_games": registered.get("minimum_independent_games"),
        "governance_policy": registered.get("governance_policy"),
        "spec_fingerprint": registered.get("spec_fingerprint"),
        "note": note,
        "auto_activation": False,
    }
    _append(row, path)
    return row


def eligible_observation(
    experiment_id: str,
    observed_at: str,
    path: Path | str = REGISTRY,
) -> bool:
    row = registrations(path).get(str(experiment_id))
    if not row:
        return False
    try:
        registered = datetime.fromisoformat(str(row["registered_at"]).replace("Z", "+00:00"))
        observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        if registered.tzinfo is None:
            registered = registered.replace(tzinfo=timezone.utc)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(timezone.utc) >= registered.astimezone(timezone.utc)
    except Exception:
        return False


def verify(path: Path | str = REGISTRY) -> dict[str, Any]:
    events = _read(path)
    regs = registrations(path)
    failures: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    legacy_governance: list[str] = []

    for event in events:
        experiment_id = str(event.get("experiment_id") or "")
        if event.get("event") == "REGISTERED":
            if experiment_id in seen:
                failures.append(f"duplicate_registration:{experiment_id}")
            seen.add(experiment_id)
            if event.get("governance_policy") == GOVERNANCE_POLICY:
                missing = [key for key in STRICT_REQUIRED if event.get(key) in (None, "", [])]
                if missing:
                    failures.append(f"strict_governance_missing:{experiment_id}:{','.join(missing)}")
                fingerprint = event.get("spec_fingerprint")
                if not fingerprint or fingerprint != spec_fingerprint(event):
                    failures.append(f"spec_fingerprint_mismatch:{experiment_id}")
            else:
                legacy_governance.append(experiment_id)
        elif experiment_id not in regs:
            failures.append(f"status_without_registration:{experiment_id}")

    if legacy_governance:
        warnings.append(
            "legacy registrations predate strict governance v2 and are not retroactively rewritten"
        )
    return {
        "schema": "pulsar-v14-experiment-registry-audit-v1",
        "valid": not failures,
        "events": len(events),
        "experiments": len(regs),
        "strict_governance_experiments": sum(
            1 for row in regs.values() if row.get("governance_policy") == GOVERNANCE_POLICY
        ),
        "legacy_governance_experiments": sorted(legacy_governance),
        "failures": failures,
        "warnings": warnings,
        "governance_policy": GOVERNANCE_POLICY,
        "policy": (
            "append-only preregistration; changed hypothesis => new experiment id; "
            "only post-registration observations may promote; new experiments seal "
            "minimum sample, analysis plan, stopping rule and promotion scope"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pulsar append-only research experiment registry")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("register")
    r.add_argument("--spec", required=True)
    r.add_argument("--registry", default=str(REGISTRY))
    b = sub.add_parser("bootstrap")
    b.add_argument("--specs", required=True)
    b.add_argument("--registry", default=str(REGISTRY))
    b.add_argument("--commit-sha")
    s = sub.add_parser("status")
    s.add_argument("experiment_id")
    s.add_argument("status")
    s.add_argument("--note")
    s.add_argument("--registry", default=str(REGISTRY))
    v = sub.add_parser("verify")
    v.add_argument("--registry", default=str(REGISTRY))
    args = parser.parse_args()

    if args.command == "register":
        out = register(json.loads(Path(args.spec).read_text(encoding="utf-8")), args.registry)
    elif args.command == "bootstrap":
        out = bootstrap_specs(args.specs, args.registry, commit_sha=args.commit_sha)
    elif args.command == "status":
        out = set_status(args.experiment_id, args.status, args.registry, note=args.note)
    else:
        out = verify(args.registry)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
