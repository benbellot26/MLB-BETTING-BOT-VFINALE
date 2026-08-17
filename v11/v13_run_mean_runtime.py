from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract

MODEL_FILE = Path("data/v13_run_mean_prior.json")
SCHEMA = "v13-run-mean-prior-v1"


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def load(path: Path = MODEL_FILE) -> dict[str,Any]:
    if not path.exists():
        return {"active":False,"status":"ABSENT"}
    try:
        d=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"active":False,"status":"INVALID","error":type(exc).__name__}
    if d.get("schema") != SCHEMA:
        return {"active":False,"status":"INCOMPATIBLE"}
    return d


def _transfer_gate(artifact: dict[str,Any]) -> tuple[bool,str]:
    generation=str(artifact.get("model_generation") or "")
    if generation != contract.MODEL_GENERATION_FINGERPRINT:
        return False,"FINAL_TRANSFER_MODEL_GENERATION_MISMATCH"
    if not artifact.get("historical_candidate_active"):
        return False,"FINAL_TRANSFER_HISTORICAL_CANDIDATE_NOT_VALIDATED"
    required=int(artifact.get("exact_transfer_required_games") or 20)
    n=int(artifact.get("exact_final_games") or artifact.get("exact_games") or 0)
    status=str(artifact.get("exact_transfer_status") or "")
    if n < required:
        return False,f"FINAL_TRANSFER_COLLECTING_{n}_OF_{required}"
    if status != "PASS_FINAL_ONLY":
        return False,f"FINAL_TRANSFER_{status or 'UNVALIDATED'}"
    return True,"PASS_FINAL_ONLY"


def apply_pair(home_mu: float, away_mu: float, phase: str, artifact: dict[str,Any] | None = None):
    artifact=load() if artifact is None else artifact
    phase=str(phase or "EARLY").upper()
    if phase != str(artifact.get("phase_scope") or "FINAL").upper():
        return home_mu,away_mu,{"active":False,"source":"none","reason":"phase_out_of_scope"}
    gate_ok,gate_reason=_transfer_gate(artifact)
    if not artifact.get("active") or not gate_ok:
        return home_mu,away_mu,{"active":False,"source":"none","reason":gate_reason,
                "historical_candidate_active":bool(artifact.get("historical_candidate_active")),
                "model_generation":artifact.get("model_generation"),
                "expected_model_generation":contract.MODEL_GENERATION_FINGERPRINT,
                "exact_transfer_games":artifact.get("exact_final_games",artifact.get("exact_games")),
                "exact_transfer_required_games":artifact.get("exact_transfer_required_games",20)}
    model=artifact.get("model") or {}
    cap=max(0.0,min(1.0,_num(model.get("max_adjustment"),.75)))
    sd=_num(model.get("slope_delta"))
    def one(mu,side):
        raw=_num(model.get(f"{side}_bias"))+sd*_num(mu)
        adj=max(-cap,min(cap,raw))
        return max(1.4,_num(mu)+adj),adj
    h,hd=one(home_mu,"home"); a,ad=one(away_mu,"away")
    return h,a,{"active":True,"source":"v13-historical-run-mean-prior","home_delta":hd,"away_delta":ad,
                "variant":artifact.get("selected_variant"),"historical_games":artifact.get("historical_games"),
                "model_generation":artifact.get("model_generation"),
                "exact_transfer_games":artifact.get("exact_final_games",artifact.get("exact_games")),
                "exact_transfer_status":artifact.get("exact_transfer_status")}
