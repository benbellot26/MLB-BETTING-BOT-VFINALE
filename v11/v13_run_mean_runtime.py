from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import probability_contract_v13 as contract

MODEL_FILE = Path("data/v13_run_mean_prior.json")
SCHEMA = "v13-run-mean-prior-v2"
MAX_RUNTIME_ADJUSTMENT = 0.15


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def load(path: Path = MODEL_FILE) -> dict[str, Any]:
    if not path.exists():
        return {"active": False, "status": "ABSENT"}
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"active": False, "status": "INVALID", "error": type(exc).__name__}
    if artifact.get("schema") != SCHEMA:
        return {"active": False, "status": "INCOMPATIBLE", "schema": artifact.get("schema")}
    return artifact


def _transfer_gate(artifact: dict[str, Any]) -> tuple[bool, str]:
    generation = str(artifact.get("model_generation") or "")
    if generation != contract.MODEL_GENERATION_FINGERPRINT:
        return False, "FINAL_TRANSFER_MODEL_GENERATION_MISMATCH"
    if not artifact.get("historical_candidate_active"):
        return False, "FINAL_TRANSFER_HISTORICAL_CANDIDATE_NOT_VALIDATED"
    walk_forward = artifact.get("walk_forward") or {}
    if not walk_forward.get("stable"):
        return False, "FINAL_TRANSFER_WALK_FORWARD_NOT_STABLE"
    required = max(60, int(artifact.get("exact_transfer_required_games") or 60))
    n = int(artifact.get("exact_final_games") or artifact.get("exact_games") or 0)
    status = str(artifact.get("exact_transfer_status") or "")
    bootstrap = artifact.get("exact_transfer_bootstrap") or {}
    if n < required:
        return False, f"FINAL_TRANSFER_COLLECTING_{n}_OF_{required}"
    if status != "PASS_FINAL_ONLY":
        return False, f"FINAL_TRANSFER_{status or 'UNVALIDATED'}"
    if bootstrap.get("passes") is not True:
        return False, "FINAL_TRANSFER_BOOTSTRAP_NOT_PASSED"
    if (artifact.get("safety") or {}).get("exact_transfer_games_excluded_from_historical_fit") is not True:
        return False, "FINAL_TRANSFER_INDEPENDENCE_NOT_ATTESTED"
    return True, "PASS_FINAL_ONLY"


def apply_pair(
    home_mu: float,
    away_mu: float,
    phase: str,
    artifact: dict[str, Any] | None = None,
):
    artifact = load() if artifact is None else artifact
    phase = str(phase or "EARLY").upper()
    if phase != str(artifact.get("phase_scope") or "FINAL").upper():
        return home_mu, away_mu, {"active": False, "source": "none", "reason": "phase_out_of_scope"}
    gate_ok, gate_reason = _transfer_gate(artifact)
    if not artifact.get("active") or not gate_ok:
        return home_mu, away_mu, {
            "active": False,
            "source": "none",
            "reason": gate_reason,
            "historical_candidate_active": bool(artifact.get("historical_candidate_active")),
            "model_generation": artifact.get("model_generation"),
            "expected_model_generation": contract.MODEL_GENERATION_FINGERPRINT,
            "historical_games": artifact.get("historical_games"),
            "walk_forward_folds": (artifact.get("walk_forward") or {}).get("folds_total"),
            "walk_forward_passed": (artifact.get("walk_forward") or {}).get("folds_passed"),
            "exact_transfer_games": artifact.get("exact_final_games", artifact.get("exact_games")),
            "exact_transfer_required_games": max(60, int(artifact.get("exact_transfer_required_games") or 60)),
        }
    model = artifact.get("model") or {}
    cap = min(MAX_RUNTIME_ADJUSTMENT, max(0.0, _num(model.get("max_adjustment"), MAX_RUNTIME_ADJUSTMENT)))
    slope_delta = _num(model.get("slope_delta"))

    def one(mu: float, side: str) -> tuple[float, float]:
        raw = _num(model.get(f"{side}_bias")) + slope_delta * _num(mu)
        adjustment = max(-cap, min(cap, raw))
        return max(1.4, _num(mu) + adjustment), adjustment

    home, home_delta = one(home_mu, "home")
    away, away_delta = one(away_mu, "away")
    return home, away, {
        "active": True,
        "source": "v13-historical-run-mean-prior-2021-2026",
        "home_delta": home_delta,
        "away_delta": away_delta,
        "runtime_cap_runs": cap,
        "variant": artifact.get("selected_variant"),
        "historical_games": artifact.get("historical_games"),
        "historical_seasons": artifact.get("historical_seasons"),
        "model_generation": artifact.get("model_generation"),
        "exact_transfer_games": artifact.get("exact_final_games", artifact.get("exact_games")),
        "exact_transfer_status": artifact.get("exact_transfer_status"),
        "exact_transfer_bootstrap": artifact.get("exact_transfer_bootstrap"),
    }
