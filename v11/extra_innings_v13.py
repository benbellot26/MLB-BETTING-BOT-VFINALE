from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

EVIDENCE_FILE = Path("data/v138_inning_evidence.json")
MIN_VALIDATED_GAMES = 200


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def validated_home_prior(path: Path = EVIDENCE_FILE) -> tuple[float, dict[str, Any]]:
    """Return the authenticated extra-innings home prior when mature.

    This prior is outcome-only historical evidence. It contains no target-game
    feature and is therefore safe to apply to the tie mass once the independent
    sample floor is met. Missing/stale/invalid artifacts fail closed to 50/50.
    """
    neutral = {
        "active": False,
        "home_probability": .5,
        "n": 0,
        "minimum_n": MIN_VALIDATED_GAMES,
        "source": "neutral-extra-innings-prior",
    }
    if not path.exists():
        return .5, {**neutral, "reason": "artifact_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return .5, {**neutral, "reason": f"artifact_invalid:{type(exc).__name__}"}
    prior = payload.get("extra_inning_prior") or {}
    n = int(prior.get("n") or payload.get("extra_inning_examples") or 0)
    p = _num(prior.get("home_probability"), .5)
    active = bool(prior.get("active")) and n >= MIN_VALIDATED_GAMES and .45 <= p <= .55
    if not active:
        return .5, {**neutral, "n": n, "reason": "insufficient_or_invalid_evidence"}
    return p, {
        "active": True,
        "home_probability": p,
        "n": n,
        "minimum_n": MIN_VALIDATED_GAMES,
        "source": "v138 authenticated MLB extra-inning outcomes",
        "evidence_schema": payload.get("schema"),
        "evidence_start": payload.get("start"),
        "evidence_end": payload.get("end"),
    }


def regulation_home_win_probability(joint: list[list[float]]) -> tuple[float,float]:
    win = tie = 0.0
    for h,row in enumerate(joint):
        for a,p in enumerate(row):
            if h > a:
                win += p
            elif h == a:
                tie += p
    return win,tie


def home_win_probability(joint: list[list[float]], extra_innings_home_prior: float | None = None) -> float:
    """Split regulation tie mass with a separately validated extra-innings prior.

    Callers that do not explicitly supply a validated prior remain neutral at
    50/50. V13Engine resolves the authenticated evidence and passes it here.
    """
    win,tie = regulation_home_win_probability(joint)
    prior = .5 if extra_innings_home_prior is None else max(.45,min(.55,_num(extra_innings_home_prior,.5)))
    return max(.001,min(.999,win+tie*prior))
