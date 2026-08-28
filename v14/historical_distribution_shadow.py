from __future__ import annotations

"""Prospective scorer for the frozen historical distribution candidate.

The candidate changes score-distribution parameters only. Its historical
evidence identity is immutable while the rolling source history may continue to
grow. A feature-contract change or any candidate tampering still fails closed.
"""

import json
from pathlib import Path
from typing import Any

from .distribution import probability_surface
from .historical_candidate_contract import validate_distribution_candidate
from .model import RunProjection

ARTIFACT = Path("data/v14_distribution_historical_candidate.json")
MANIFEST = Path("data/v138_dataset_manifest.json")
ROLE = "SHADOW_ONLY"


def _manifest(path: Path | str = MANIFEST) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def validate_artifact(payload: Any, manifest_path: Path | str = MANIFEST) -> dict[str, Any]:
    return validate_distribution_candidate(payload, _manifest(manifest_path))


def load(artifact_path: Path | str = ARTIFACT, manifest_path: Path | str = MANIFEST) -> dict[str, Any]:
    try:
        artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return validate_artifact(artifact, manifest_path)


def evaluate(prediction: dict[str, Any], artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = load() if artifact is None else validate_artifact(artifact)
    base = {
        "schema": "pulsar-v14-historical-distribution-shadow-v2",
        "role": ROLE,
        "auto_activation": False,
        "champion_impact": False,
        "native_live_confirmation_required": True,
    }
    if not evidence:
        return {**base, "status": "COLLECTING", "reason": "validated immutable historical distribution artifact unavailable"}

    run = prediction.get("run_projection") or {}
    champion_probs = prediction.get("probabilities") or {}
    params = evidence.get("candidate_parameters") or {}
    required = (
        run.get("home_mu"),
        run.get("away_mu"),
        prediction.get("total_line"),
        params.get("dispersion"),
        params.get("environment_sigma"),
    )
    if any(value is None for value in required):
        return {**base, "status": "COLLECTING", "reason": "prediction fields required for shadow distribution missing"}

    projection = RunProjection(
        game_pk=str(prediction.get("game_pk") or "unknown"),
        game_date=str(prediction.get("game_date") or ""),
        analyzed_at=str(prediction.get("analyzed_at") or ""),
        home=str(prediction.get("home") or "home"),
        away=str(prediction.get("away") or "away"),
        home_mu=float(run["home_mu"]),
        away_mu=float(run["away_mu"]),
        total_line=float(prediction["total_line"]),
        phase=str(prediction.get("phase") or "EARLY"),
        dispersion=float(params["dispersion"]),
        environment_sigma=float(params["environment_sigma"]),
        extra_innings_home_probability=float(run.get("extra_innings_home_probability") or 0.5),
        source_generation=str(prediction.get("model_generation") or ""),
    )
    surface, tail = probability_surface(projection)
    candidate = surface.as_dict()
    deltas = {key: candidate[key] - float(champion_probs[key]) for key in candidate if champion_probs.get(key) is not None}
    return {
        **base,
        "status": "READY_SHADOW",
        "candidate_id": evidence.get("candidate_id"),
        "candidate_fingerprint": evidence.get("candidate_fingerprint"),
        "evidence_run_id": evidence.get("source_run_id"),
        "evidence_artifact_sha256": ((evidence.get("source_validation_artifact") or {}).get("sha256")),
        "frozen_at": evidence.get("frozen_at"),
        "candidate_parameters": params,
        "candidate_probabilities": candidate,
        "champion_probabilities": {key: champion_probs.get(key) for key in candidate},
        "probability_delta": deltas,
        "tail_mass": tail,
    }
