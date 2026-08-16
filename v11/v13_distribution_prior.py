from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODEL_FILE = Path("data/v13_distribution_prior.json")
SCHEMA = "v13-distribution-prior-v1"


def load(path: Path = MODEL_FILE) -> dict[str, Any]:
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schema":SCHEMA,"active":False,"status":"ABSENT_OR_INVALID","error":type(exc).__name__}
    required=(
        data.get("schema")==SCHEMA,
        data.get("active") is True,
        str(data.get("phase_scope") or "").upper()=="FINAL",
        str(data.get("variant") or "")=="dispersion_only",
        data.get("market_data_used") is False,
        data.get("historical_odds_used") is False,
        int(data.get("warm_games") or 0)>=1600,
        int(data.get("validation_games") or 0)>=300,
        int(data.get("test_games") or 0)>=300,
        int(data.get("exact_replay_games") or 0)>=20,
        float(data.get("validation_nll_gain") or 0)>0,
        float(data.get("test_nll_gain") or 0)>0,
        float(data.get("exact_replay_nll_gain") or 0)>=0,
        2.0 <= float(data.get("dispersion") or 0) <= 10.0,
        abs(float(data.get("environment_sigma") or 0)-.08) < 1e-12,
    )
    if not all(required):
        return {"schema":SCHEMA,"active":False,"status":"EVIDENCE_GATE_FAIL"}
    data["status"]="ACTIVE_VALIDATED_FINAL_ONLY"
    return data


def apply(dispersion: float, env_sigma: float, phase: str, path: Path = MODEL_FILE) -> tuple[float,float,dict[str,Any]]:
    model=load(path)
    if str(phase or "").upper()!="FINAL" or not model.get("active"):
        return dispersion,env_sigma,{"active":False,"source":"none"}
    return float(model["dispersion"]),float(model["environment_sigma"]),{
        "active":True,
        "source":"v13-validated-historical-distribution",
        "variant":model.get("variant"),
        "warm_games":model.get("warm_games"),
        "validation_nll_gain":model.get("validation_nll_gain"),
        "test_nll_gain":model.get("test_nll_gain"),
        "exact_replay_nll_gain":model.get("exact_replay_nll_gain"),
    }
