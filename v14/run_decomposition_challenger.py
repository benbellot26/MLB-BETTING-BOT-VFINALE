from __future__ import annotations

"""Research-only opponent run-prevention decomposition for Pulsar V14.

The champion currently blends team ERA and starter quality. This challenger
exposes a cleaner future architecture: starter quality weighted by expected
starter innings, bullpen quality weighted by expected bullpen innings, then a
separate defense factor. It does not auto-activate or modify production output.
"""

import math
from typing import Any

ROLE = "CHALLENGER_ONLY"


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def opponent_factor(
    *,
    starter_factor: float,
    bullpen_factor: float,
    defense_factor: float,
    expected_starter_innings: float,
) -> dict[str, Any]:
    """Combine independent run-prevention components without double counting."""
    starter = _clip(float(starter_factor), 0.70, 1.35)
    bullpen = _clip(float(bullpen_factor), 0.70, 1.35)
    defense = _clip(float(defense_factor), 0.85, 1.15)
    starter_ip = _clip(float(expected_starter_innings), 0.0, 9.0)
    bullpen_ip = 9.0 - starter_ip
    pitching = (starter_ip / 9.0) * starter + (bullpen_ip / 9.0) * bullpen
    combined = _clip(pitching * defense, 0.65, 1.45)
    return {
        "schema": "pulsar-v14-run-decomposition-challenger-v1",
        "role": ROLE,
        "auto_activation": False,
        "starter_factor": starter,
        "bullpen_factor": bullpen,
        "defense_factor": defense,
        "expected_starter_innings": starter_ip,
        "expected_bullpen_innings": bullpen_ip,
        "pitching_factor": pitching,
        "opponent_factor": combined,
        "market_probability_used_as_feature": False,
    }


def build(
    *,
    starter_usage: dict[str, Any] | None,
    starter_factor: Any,
    bullpen_factor: Any,
    defense_factor: Any,
) -> dict[str, Any]:
    usage = starter_usage if isinstance(starter_usage, dict) else {}
    starter = _num(starter_factor)
    bullpen = _num(bullpen_factor)
    defense = _num(defense_factor)
    expected_ip = _num(usage.get("expected_innings"))
    missing = [
        name
        for name, value in (
            ("starter_factor", starter),
            ("bullpen_factor", bullpen),
            ("defense_factor", defense),
            ("expected_starter_innings", expected_ip),
        )
        if value is None
    ]
    if missing:
        return {
            "schema": "pulsar-v14-run-decomposition-challenger-v1",
            "role": ROLE,
            "status": "COLLECTING",
            "auto_activation": False,
            "missing": missing,
            "reason": "independent starter/bullpen/defense evidence incomplete",
        }
    out = opponent_factor(
        starter_factor=starter,
        bullpen_factor=bullpen,
        defense_factor=defense,
        expected_starter_innings=expected_ip,
    )
    out["status"] = "READY_SHADOW"
    return out
