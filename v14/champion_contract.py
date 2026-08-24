from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# Frozen V13.10 champion defaults. These are not challenger values: they are the
# parameters currently used by the production champion when no separately
# validated replacement is active.
CHAMPION_DISPERSION = 7.5
CHAMPION_ENVIRONMENT_SIGMA = 0.08
MAX_RUNS_MATRIX = 24
MAX_RUNS_HARD = 60
SCORE_TAIL_TOLERANCE = 1e-6
MIN_EXTRA_INNINGS_GAMES = 200
EXTRA_INNINGS_EVIDENCE = Path("data/v138_inning_evidence.json")


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def validated_extra_innings_home_probability(path: Path = EXTRA_INNINGS_EVIDENCE) -> tuple[float, dict[str, Any]]:
    """Clean V14 port of the active V13.10 extra-innings contract.

    The evidence is historical outcome-only evidence and is never a target-game
    feature. Missing, malformed or immature evidence fails closed to 50/50.
    """
    neutral = {
        "active": False,
        "home_probability": 0.5,
        "n": 0,
        "minimum_n": MIN_EXTRA_INNINGS_GAMES,
        "source": "neutral-extra-innings-prior",
    }
    if not path.exists():
        return 0.5, {**neutral, "reason": "artifact_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return 0.5, {**neutral, "reason": f"artifact_invalid:{type(exc).__name__}"}
    prior = payload.get("extra_inning_prior") or {}
    n = int(prior.get("n") or payload.get("extra_inning_examples") or 0)
    probability = float(_num(prior.get("home_probability"), 0.5) or 0.5)
    active = bool(prior.get("active")) and n >= MIN_EXTRA_INNINGS_GAMES and 0.45 <= probability <= 0.55
    if not active:
        return 0.5, {**neutral, "n": n, "reason": "insufficient_or_invalid_evidence"}
    return probability, {
        "active": True,
        "home_probability": probability,
        "n": n,
        "minimum_n": MIN_EXTRA_INNINGS_GAMES,
        "source": "authenticated MLB extra-inning outcomes",
        "evidence_schema": payload.get("schema"),
        "evidence_start": payload.get("start"),
        "evidence_end": payload.get("end"),
    }


def parameters_from_champion_result(result: dict[str, Any]) -> dict[str, Any]:
    """Read only champion score-distribution state, never champion probabilities.

    During parity migration V14 is allowed to consume the V13.10 run means plus
    the score-distribution configuration that produced them. Probability fields,
    market fields, selectors and staking fields are explicitly outside this
    boundary.
    """
    features = result.get("features") or {}
    model = result.get("model") or {}

    dispersion = _num(features.get("run_dispersion"), _num(model.get("dispersion"), CHAMPION_DISPERSION))
    environment_sigma = _num(
        features.get("run_environment_sigma"),
        _num(model.get("environment_sigma"), CHAMPION_ENVIRONMENT_SIGMA),
    )
    if dispersion is None or dispersion <= 0:
        dispersion = CHAMPION_DISPERSION
    if environment_sigma is None or not 0.0 <= environment_sigma <= 0.30:
        environment_sigma = CHAMPION_ENVIRONMENT_SIGMA

    extra = _num(features.get("extra_innings_home_probability"))
    extra_meta = features.get("extra_innings_prior") if isinstance(features.get("extra_innings_prior"), dict) else None
    if extra is None or not 0.45 <= extra <= 0.55:
        extra, loaded_meta = validated_extra_innings_home_probability()
        extra_meta = loaded_meta

    return {
        "dispersion": float(dispersion),
        "environment_sigma": float(environment_sigma),
        "extra_innings_home_probability": float(extra),
        "extra_innings_meta": extra_meta or {},
        "source": "frozen-v13.10-champion-score-contract",
    }
