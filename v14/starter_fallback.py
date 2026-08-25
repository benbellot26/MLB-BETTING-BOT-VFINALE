from __future__ import annotations

"""Conservative starter fallback helpers.

When official MLB starter representations disagree, Pulsar must keep the game in
its slate without trusting a potentially stale pitcher identity. The conflicted
side is therefore neutralized to the league-average starter path by removing the
probablePitcher identity before rebuilding structural inputs.
"""

from copy import deepcopy
from typing import Any


def degraded_sides_from_evidence(evidence: dict[str, Any], phase: str) -> list[str]:
    phase = str(phase or "EARLY").upper()
    if phase == "EARLY":
        return []
    degraded: list[str] = []
    for side in ("away", "home"):
        row = evidence.get(side) or {}
        sources = {src.get("source"): src for src in row.get("sources") or []}
        schedule = sources.get("schedule.probablePitcher") or {}
        feed = sources.get("feed.gameData.probablePitchers") or {}
        box = sources.get("boxscore.pitchers[0]") or {}
        schedule_ok = bool(schedule.get("available"))
        feed_ok = bool(feed.get("available"))
        agreement = schedule_ok and feed_ok and str(schedule.get("id")) == str(feed.get("id"))
        box_conflict = bool(box.get("available")) and schedule_ok and str(box.get("id")) != str(schedule.get("id"))
        if not agreement or box_conflict:
            degraded.append(side)
    return degraded


def neutralize_probable_pitchers(game: dict[str, Any], sides: list[str]) -> dict[str, Any]:
    sanitized = deepcopy(game)
    teams = sanitized.setdefault("teams", {})
    for side in sides:
        team = teams.setdefault(side, {})
        team["probablePitcher"] = {}
    return sanitized


def degradation_summary(evidence: dict[str, Any], sides: list[str]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for side in sides:
        row = evidence.get(side) or {}
        details[side] = {
            "sources": row.get("sources") or [],
            "distinct_pitcher_ids": row.get("distinct_pitcher_ids") or [],
            "reason": "starter identity not safely confirmed; neutral league-average starter fallback used",
        }
    return {
        "degraded": bool(sides),
        "sides": list(sides),
        "mode": "NEUTRAL_STARTER_FALLBACK" if sides else "NONE",
        "details": details,
    }
