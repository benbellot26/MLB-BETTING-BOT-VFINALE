from __future__ import annotations

"""Identity and integrity contract for frozen historical shadow candidates.

Historical candidates are immutable research artifacts.  Their evidence identity
must remain stable while the rolling source dataset is allowed to grow.  Only a
feature-contract change invalidates an otherwise intact frozen candidate.
"""

from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any

TEAM_SCHEMA = "pulsar-v14-historical-team-run-candidate-v2"
DISTRIBUTION_SCHEMA = "pulsar-v14-historical-distribution-candidate-v2"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def candidate_fingerprint(payload: dict[str, Any]) -> str:
    canonical = dict(payload)
    canonical.pop("candidate_fingerprint", None)
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _common_valid(payload: Any, *, schema: str, manifest: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not isinstance(manifest, dict):
        return False
    if payload.get("schema") != schema:
        return False
    if payload.get("role") != "SHADOW_ONLY" or payload.get("status") != "HISTORICAL_VALIDATED_SHADOW":
        return False
    if payload.get("auto_activation") is not False or payload.get("champion_impact") is not False:
        return False
    if payload.get("native_live_confirmation_required") is not True:
        return False
    if not str(payload.get("candidate_id") or "").strip():
        return False
    if not _HEX40.fullmatch(str(payload.get("source_commit_sha") or "")):
        return False
    try:
        if int(payload.get("source_run_id") or 0) <= 0:
            return False
    except Exception:
        return False
    try:
        datetime.fromisoformat(str(payload.get("frozen_at") or "").replace("Z", "+00:00"))
    except Exception:
        return False

    feature_contract = str(payload.get("feature_contract_sha256") or "")
    if not _HEX64.fullmatch(feature_contract):
        return False
    if feature_contract != str(manifest.get("feature_contract_sha256") or ""):
        return False

    source_artifact = payload.get("source_validation_artifact") or {}
    try:
        if int(source_artifact.get("id") or 0) <= 0:
            return False
    except Exception:
        return False
    evidence_sha = str(source_artifact.get("sha256") or "")
    if not _HEX64.fullmatch(evidence_sha):
        return False

    historical = payload.get("historical_evidence") or {}
    try:
        if int(historical.get("games") or 0) <= 0:
            return False
    except Exception:
        return False
    if str(historical.get("validation_artifact_sha256") or "") != evidence_sha:
        return False
    split = historical.get("split") or {}
    for key in ("tuning_2021_2024", "validation_2025", "frozen_test_2026"):
        try:
            if int(split.get(key) or 0) <= 0:
                return False
        except Exception:
            return False
    if split.get("frozen_2026_used_for_parameter_selection") is not False:
        return False

    fingerprint = str(payload.get("candidate_fingerprint") or "")
    if not _HEX64.fullmatch(fingerprint):
        return False
    return fingerprint == candidate_fingerprint(payload)


def validate_team_candidate(payload: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    if not _common_valid(payload, schema=TEAM_SCHEMA, manifest=manifest):
        return {}
    params = payload.get("parameters") or {}
    required = (
        "season_prior_games",
        "recent14_weight",
        "recent7_weight",
        "offense_weight",
        "home_advantage_runs",
        "park_weight",
    )
    if any(not _finite_number(params.get(key)) for key in required):
        return {}
    return payload


def validate_distribution_candidate(payload: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    if not _common_valid(payload, schema=DISTRIBUTION_SCHEMA, manifest=manifest):
        return {}
    candidate = payload.get("candidate_parameters") or {}
    champion = payload.get("champion_parameters") or {}
    for params in (candidate, champion):
        if not _finite_number(params.get("dispersion")) or not _finite_number(params.get("environment_sigma")):
            return {}
        if float(params["dispersion"]) <= 0 or float(params["environment_sigma"]) < 0:
            return {}
    return payload
