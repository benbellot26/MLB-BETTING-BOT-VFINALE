from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import v138_audit_features as audit_features
from . import v138_research_models as models

MODEL_FILE=Path("data/v138_research_models.json")


def load() -> dict[str,Any]:
    if not MODEL_FILE.exists():return {"status":"ABSENT"}
    try:return json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    except Exception:return {"status":"INVALID"}


def attach(result: dict[str,Any],artifact: dict[str,Any] | None=None,statcast_priors: dict[str,Any] | None=None) -> dict[str,Any]:
    """Attach research diagnostics only; never mutate champion run means/options."""
    artifact=load() if artifact is None else artifact
    payload={"research_only":True,"affects_champion":False,"affects_selector":False,"affects_staking":False,
             "advanced_context":audit_features.build_advanced_context(result,statcast_priors)}
    if artifact.get("status")!="TRAINED_RESEARCH_ONLY":
        payload.update({"status":"MODEL_NOT_TRAINED","model_status":artifact.get("status")});result["shadow_v138"]=payload;return result
    # Historical model vector requires the compact reconstructed feature envelope;
    # live runtime may not expose that exact contract yet. Fail neutral rather than
    # fabricate a conversion from incompatible fields.
    if not ((result.get("features") or {}).get("home_team_form") and (result.get("features") or {}).get("away_team_form")):
        payload.update({"status":"FEATURE_CONTRACT_NOT_AVAILABLE_LIVE"});result["shadow_v138"]=payload;return result
    p=models.predict(artifact,result)
    payload.update({"status":"ACTIVE_SHADOW" if p.get("available") else "UNAVAILABLE","prediction":p})
    result["shadow_v138"]=payload;return result
