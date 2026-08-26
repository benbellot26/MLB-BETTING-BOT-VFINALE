from __future__ import annotations

"""Prospective native-live scorer for the historically validated team-run candidate.

Historical evidence only nominated this challenger against the strict team-history
reference.  This module therefore keeps the candidate fully separate from the
champion and records an exact paired native-live shadow using the champion score
distribution.  Dataset hashes are checked before any shadow score is produced.
"""

import json
from pathlib import Path
from typing import Any

from .champion_contract import CHAMPION_DISPERSION, CHAMPION_ENVIRONMENT_SIGMA
from .distribution import probability_surface
from .historical_team_challenger import candidate_runs
from .model import RunProjection

ARTIFACT=Path("data/v14_team_run_historical_candidate.json")
MANIFEST=Path("data/v138_dataset_manifest.json")
ROLE="SHADOW_ONLY"


def load(artifact_path:Path|str=ARTIFACT,manifest_path:Path|str=MANIFEST)->dict[str,Any]:
    try:
        artifact=json.loads(Path(artifact_path).read_text(encoding="utf-8")); manifest=json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    dataset=artifact.get("dataset") or {}
    if artifact.get("schema")!="pulsar-v14-historical-team-run-candidate-v1": return {}
    if artifact.get("status")!="HISTORICAL_VALIDATED_SHADOW" or artifact.get("auto_activation") is not False: return {}
    if artifact.get("champion_impact") is not False or artifact.get("native_live_confirmation_required") is not True: return {}
    if dataset.get("dataset_content_sha256")!=manifest.get("dataset_content_sha256"): return {}
    if dataset.get("feature_contract_sha256")!=manifest.get("feature_contract_sha256"): return {}
    params=artifact.get("parameters") or {}
    required=("season_prior_games","recent14_weight","recent7_weight","offense_weight","home_advantage_runs","park_weight")
    if any(k not in params for k in required): return {}
    return artifact


def _feature(team_history:dict[str,Any],park_factor:float|None=None)->dict[str,Any]:
    features={"home_team_form":team_history.get("home") or {},"away_team_form":team_history.get("away") or {}}
    if park_factor is not None: features["park_prior"]={"run_factor":park_factor}
    return {"features":features}


def evaluate(prediction:dict[str,Any],team_history:dict[str,Any],*,park_factor:float|None=None,artifact:dict[str,Any]|None=None)->dict[str,Any]:
    evidence=load() if artifact is None else artifact
    base={"schema":"pulsar-v14-historical-team-run-shadow-v1","role":ROLE,"auto_activation":False,"champion_impact":False,"native_live_confirmation_required":True}
    if not evidence: return {**base,"status":"COLLECTING","reason":"validated hash-bound historical team-run artifact unavailable"}
    if team_history.get("status")!="READY_SHADOW" or team_history.get("point_in_time") is not True:
        return {**base,"status":"COLLECTING","reason":"strict PIT team-history matchup unavailable"}
    home_hist=team_history.get("home") or {}; away_hist=team_history.get("away") or {}
    if int((home_hist.get("season_to_date") or {}).get("games") or 0)<=0 or int((away_hist.get("season_to_date") or {}).get("games") or 0)<=0:
        return {**base,"status":"COLLECTING","reason":"team-history season sample unavailable"}
    run=prediction.get("run_projection") or {}; probs=prediction.get("probabilities") or {}; total_line=prediction.get("total_line")
    required=(run.get("home_mu"),run.get("away_mu"),total_line)
    if any(v is None for v in required): return {**base,"status":"COLLECTING","reason":"champion prediction fields required for paired shadow missing"}
    try:
        home_mu,away_mu=candidate_runs(_feature(team_history,park_factor),evidence.get("parameters") or {})
        projection=RunProjection(
            game_pk=str(prediction.get("game_pk") or "unknown"),game_date=str(prediction.get("game_date") or ""),analyzed_at=str(prediction.get("analyzed_at") or ""),
            home=str(prediction.get("home") or "home"),away=str(prediction.get("away") or "away"),home_mu=home_mu,away_mu=away_mu,total_line=float(total_line),
            phase=str(prediction.get("phase") or "EARLY"),dispersion=CHAMPION_DISPERSION,environment_sigma=CHAMPION_ENVIRONMENT_SIGMA,
            extra_innings_home_probability=float(run.get("extra_innings_home_probability") or .5),source_generation=str(prediction.get("model_generation") or "")
        )
        surface,tail=probability_surface(projection); candidate=surface.as_dict()
    except Exception as exc:
        return {**base,"status":"COLLECTING","reason":f"shadow evaluation failed: {type(exc).__name__}: {exc}"}
    deltas={k:candidate[k]-float(probs[k]) for k in candidate if probs.get(k) is not None}
    return {
        **base,"status":"READY_SHADOW","evidence_run_id":evidence.get("source_run_id"),"frozen_at":evidence.get("frozen_at"),
        "dataset_content_sha256":((evidence.get("dataset") or {}).get("dataset_content_sha256")),"parameters":evidence.get("parameters") or {},
        "candidate_run_projection":{"home_mu":home_mu,"away_mu":away_mu,"dispersion":CHAMPION_DISPERSION,"environment_sigma":CHAMPION_ENVIRONMENT_SIGMA},
        "champion_run_projection":{"home_mu":float(run["home_mu"]),"away_mu":float(run["away_mu"]),"dispersion":run.get("dispersion"),"environment_sigma":run.get("environment_sigma")},
        "run_delta":{"home_mu":home_mu-float(run["home_mu"]),"away_mu":away_mu-float(run["away_mu"])},
        "candidate_probabilities":candidate,"champion_probabilities":{k:probs.get(k) for k in candidate},"probability_delta":deltas,"tail_mass":tail,
        "comparison_contract":"candidate team-run means + current champion distribution versus exact native V14 champion prediction"
    }
