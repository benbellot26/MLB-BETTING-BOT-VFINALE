from __future__ import annotations

"""Normalize V13 PIT feature-store shapes for the isolated V14 context layer.

No values are fetched here and no postgame information is introduced. The
adapter only aliases fields already present in a V13 pregame feature row.
"""

from copy import deepcopy
from typing import Any

ADAPTER_SCHEMA = "v14-v13-context-adapter-v1"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_reliever(reliever: dict[str, Any]) -> dict[str, Any]:
    out = dict(reliever)
    pitches_3d = _num(out.get("pitches_3d"))
    appearances = _num(out.get("appearances_recent"))
    days_used = _num(out.get("days_used"))
    availability = _num(out.get("availability"))

    if out.get("pitches_last_3d") is None and pitches_3d is not None:
        out["pitches_last_3d"] = pitches_3d
    if out.get("uses_last_3d") is None and appearances is not None:
        out["uses_last_3d"] = appearances

    if "taxed" not in out:
        out["taxed"] = bool(
            (pitches_3d is not None and pitches_3d >= 45)
            or (days_used is not None and days_used >= 3)
        )
    if "likely_unavailable" not in out and availability is not None:
        out["likely_unavailable"] = availability < 0.35
    return out


def adapt_feature_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    out = deepcopy(row)

    features = out.get("features")
    if not isinstance(features, dict):
        features = {}
        out["features"] = features
    bullpen = features.get("bullpen")
    if isinstance(bullpen, dict):
        for side in ("home", "away"):
            snap = bullpen.get(side)
            if not isinstance(snap, dict):
                continue
            relievers = snap.get("relievers")
            if isinstance(relievers, list):
                snap["relievers"] = [
                    _normalize_reliever(r) if isinstance(r, dict) else r
                    for r in relievers
                ]

    rich = out.get("rich_modules")
    if not isinstance(rich, dict):
        rich = {}
        out["rich_modules"] = rich

    for side in ("home", "away"):
        side_block = rich.get(side)
        if not isinstance(side_block, dict):
            continue
        pitch_matchup = side_block.get("pitch_matchup")
        if isinstance(pitch_matchup, dict):
            rich.setdefault(f"{side}_lineup_pitch_matchup", deepcopy(pitch_matchup))

    out["v14_adapter"] = {
        "schema": ADAPTER_SCHEMA,
        "source_values_only": True,
        "point_in_time_inherited": out.get("point_in_time") is True,
        "postgame_data_added": False,
    }
    return out
