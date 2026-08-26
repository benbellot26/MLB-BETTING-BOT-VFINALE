from __future__ import annotations

"""Prospective shadow scorer for the historically validated distribution candidate.

The candidate changes only score-distribution parameters, never run means. Its
parameters are frozen in a hash-bound evidence artifact produced from the
strict 2021-2026 PIT laboratory. This module can collect paired native-live
predictions but cannot alter the champion or betting authorization.
"""

import json
from pathlib import Path
from typing import Any

from .distribution import probability_surface
from .model import RunProjection

ARTIFACT=Path("data/v14_distribution_historical_candidate.json")
MANIFEST=Path("data/v138_dataset_manifest.json")
ROLE="SHADOW_ONLY"


def load(artifact_path:Path|str=ARTIFACT,manifest_path:Path|str=MANIFEST)->dict[str,Any]:
    try:
        artifact=json.loads(Path(artifact_path).read_text(encoding="utf-8"));manifest=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception:return {}
    dataset=artifact.get("dataset") or {}
    if artifact.get("schema")!="pulsar-v14-historical-distribution-candidate-v1":return {}
    if artifact.get("status")!="HISTORICAL_VALIDATED_SHADOW" or artifact.get("auto_activation") is not False:return {}
    if dataset.get("dataset_content_sha256")!=manifest.get("dataset_content_sha256"):return {}
    if dataset.get("feature_contract_sha256")!=manifest.get("feature_contract_sha256"):return {}
    return artifact


def evaluate(prediction:dict[str,Any],artifact:dict[str,Any]|None=None)->dict[str,Any]:
    evidence=load() if artifact is None else artifact
    base={"schema":"pulsar-v14-historical-distribution-shadow-v1","role":ROLE,"auto_activation":False,"champion_impact":False,"native_live_confirmation_required":True}
    if not evidence:return {**base,"status":"COLLECTING","reason":"validated hash-bound historical distribution artifact unavailable"}
    run=prediction.get("run_projection") or {};champion_probs=prediction.get("probabilities") or {};params=evidence.get("candidate_parameters") or {}
    required=(run.get("home_mu"),run.get("away_mu"),prediction.get("total_line"),params.get("dispersion"),params.get("environment_sigma"))
    if any(v is None for v in required):return {**base,"status":"COLLECTING","reason":"prediction fields required for shadow distribution missing"}
    projection=RunProjection(
        game_pk=str(prediction.get("game_pk") or "unknown"),game_date=str(prediction.get("game_date") or ""),analyzed_at=str(prediction.get("analyzed_at") or ""),
        home=str(prediction.get("home") or "home"),away=str(prediction.get("away") or "away"),home_mu=float(run["home_mu"]),away_mu=float(run["away_mu"]),
        total_line=float(prediction["total_line"]),phase=str(prediction.get("phase") or "EARLY"),dispersion=float(params["dispersion"]),environment_sigma=float(params["environment_sigma"]),
        extra_innings_home_probability=float(run.get("extra_innings_home_probability") or .5),source_generation=str(prediction.get("model_generation") or "")
    )
    surface,tail=probability_surface(projection);candidate=surface.as_dict();deltas={k:candidate[k]-float(champion_probs[k]) for k in candidate if k in champion_probs}
    return {**base,"status":"READY_SHADOW","evidence_run_id":evidence.get("source_run_id"),"dataset_content_sha256":((evidence.get("dataset") or {}).get("dataset_content_sha256")),"candidate_parameters":params,"candidate_probabilities":candidate,"champion_probabilities":{k:champion_probs.get(k) for k in candidate},"probability_delta":deltas,"tail_mass":tail}
