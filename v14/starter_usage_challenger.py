from __future__ import annotations

"""Expected starter-depth research feature for Pulsar V14.

This module is deliberately challenger-only. It turns point-in-time season
workload (and optional recent-start workload when available) into an expected
starter innings estimate. It never changes champion probabilities by itself.
"""

import math
from typing import Any

ROLE = "CHALLENGER_ONLY"
LEAGUE_STARTER_IP = 5.2
MIN_EXPECTED_IP = 3.0
MAX_EXPECTED_IP = 7.2


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _recent_values(starter: dict[str, Any]) -> tuple[list[float], list[float]]:
    innings: list[float] = []
    pitches: list[float] = []
    for row in starter.get("recent_starts") or []:
        if not isinstance(row, dict):
            continue
        ip = _num(row.get("innings") or row.get("inningsPitched"))
        pc = _num(row.get("pitches") or row.get("pitchesThrown"))
        if ip is not None and 0 <= ip <= 9:
            innings.append(ip)
        if pc is not None and 0 <= pc <= 140:
            pitches.append(pc)
    return innings[:8], pitches[:8]


def estimate(starter: dict[str, Any] | None) -> dict[str, Any]:
    data = starter if isinstance(starter, dict) else {}
    starts = int(max(0.0, _num(data.get("gamesStarted")) or 0.0))
    season_ip_per_start = _num(data.get("inningsPerStart"))
    if season_ip_per_start is None:
        total_ip = _num(data.get("inningsPitched"))
        if total_ip is not None and starts > 0:
            season_ip_per_start = total_ip / starts

    recent_ip, recent_pitches = _recent_values(data)
    if season_ip_per_start is None and not recent_ip:
        return {
            "schema": "pulsar-v14-starter-usage-challenger-v1",
            "role": ROLE,
            "status": "COLLECTING",
            "auto_activation": False,
            "expected_innings": LEAGUE_STARTER_IP,
            "confidence": 0.0,
            "reason": "starter workload evidence unavailable",
        }

    season_estimate = _clip(
        season_ip_per_start if season_ip_per_start is not None else LEAGUE_STARTER_IP,
        MIN_EXPECTED_IP,
        MAX_EXPECTED_IP,
    )
    season_confidence = _clip(starts / 18.0, 0.0, 1.0)

    if recent_ip:
        weights = [0.82 ** i for i in range(len(recent_ip))]
        recent_estimate = sum(value * weight for value, weight in zip(recent_ip, weights)) / sum(weights)
        recent_confidence = _clip(len(recent_ip) / 5.0, 0.0, 1.0)
        recent_weight = 0.55 * recent_confidence
        expected = (1.0 - recent_weight) * season_estimate + recent_weight * recent_estimate
    else:
        recent_estimate = None
        recent_confidence = 0.0
        expected = season_estimate

    pitch_adjustment = 0.0
    if recent_pitches:
        avg_pitches = sum(recent_pitches) / len(recent_pitches)
        if avg_pitches < 80:
            pitch_adjustment = -min(0.45, (80 - avg_pitches) * 0.018)
        elif avg_pitches > 96:
            pitch_adjustment = min(0.25, (avg_pitches - 96) * 0.012)
        expected += pitch_adjustment
    else:
        avg_pitches = None

    expected = _clip(expected, MIN_EXPECTED_IP, MAX_EXPECTED_IP)
    confidence = _clip(0.70 * season_confidence + 0.30 * recent_confidence, 0.0, 1.0)
    return {
        "schema": "pulsar-v14-starter-usage-challenger-v1",
        "role": ROLE,
        "status": "READY_SHADOW" if starts >= 3 else "COLLECTING",
        "auto_activation": False,
        "expected_innings": expected,
        "expected_bullpen_innings": max(0.0, 9.0 - expected),
        "confidence": confidence,
        "season_starts": starts,
        "season_innings_per_start": season_ip_per_start,
        "recent_starts_n": len(recent_ip),
        "recent_innings_estimate": recent_estimate,
        "recent_average_pitches": avg_pitches,
        "pitch_count_adjustment_innings": pitch_adjustment,
        "market_probability_used_as_feature": False,
    }
