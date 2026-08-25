from __future__ import annotations

"""Cross-check starting pitchers before LATE/FINAL publication.

The schedule probablePitcher field is not sufficient on its own: MLB can update
or temporarily expose stale probable-pitcher identities. This module compares
multiple MLB representations and fails closed when they disagree.
"""

from typing import Any, Callable

from .acquisition import http_json

MLB_API = "https://statsapi.mlb.com/api/"
MLBGetter = Callable[[str, dict[str, Any]], Any]


def _mlb(path: str, params: dict[str, Any] | None = None, *, getter: MLBGetter = http_json) -> Any:
    return getter(MLB_API + path.lstrip("/"), params or {})


def _id_name(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    pid = value.get("id")
    name = value.get("fullName") or value.get("name")
    return (str(pid) if pid is not None else None, str(name) if name else None)


def _schedule_source(game: dict[str, Any], side: str) -> dict[str, Any]:
    probable = ((((game.get("teams") or {}).get(side) or {}).get("probablePitcher")) or {})
    pid, name = _id_name(probable)
    return {"source": "schedule.probablePitcher", "id": pid, "name": name, "available": bool(pid)}


def _feed_source(feed: dict[str, Any], side: str) -> dict[str, Any]:
    probable = (((feed.get("gameData") or {}).get("probablePitchers") or {}).get(side) or {})
    pid, name = _id_name(probable)
    return {"source": "feed.gameData.probablePitchers", "id": pid, "name": name, "available": bool(pid)}


def _boxscore_source(box: dict[str, Any], side: str) -> dict[str, Any]:
    team = ((box.get("teams") or {}).get(side) or {})
    pitcher_ids = list(team.get("pitchers") or [])
    if not pitcher_ids:
        return {"source": "boxscore.pitchers[0]", "id": None, "name": None, "available": False}
    pid = str(pitcher_ids[0])
    player = (team.get("players") or {}).get(f"ID{pid}") or {}
    person = player.get("person") or {}
    return {
        "source": "boxscore.pitchers[0]",
        "id": pid,
        "name": person.get("fullName"),
        "available": True,
    }


def _normalize_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in sources if row.get("available") and row.get("id")]


def _side_evidence(game: dict[str, Any], feed: dict[str, Any], box: dict[str, Any], side: str) -> dict[str, Any]:
    all_sources = [_schedule_source(game, side), _feed_source(feed, side), _boxscore_source(box, side)]
    available = _normalize_sources(all_sources)
    ids = {str(row["id"]) for row in available}
    return {
        "side": side,
        "sources": all_sources,
        "available_sources": len(available),
        "distinct_pitcher_ids": sorted(ids),
        "consensus": len(ids) == 1 and len(available) >= 2,
        "consensus_id": next(iter(ids)) if len(ids) == 1 else None,
        "conflict": len(ids) > 1,
    }


def starter_integrity_evidence(game: dict[str, Any], *, getter: MLBGetter = http_json) -> dict[str, Any]:
    game_pk = game.get("gamePk")
    if game_pk is None:
        raise ValueError("game missing gamePk for starter integrity check")
    try:
        feed = _mlb(f"v1.1/game/{game_pk}/feed/live", getter=getter) or {}
    except Exception:
        feed = {}
    try:
        box = _mlb(f"v1/game/{game_pk}/boxscore", getter=getter) or {}
    except Exception:
        box = {}
    return {
        "game_pk": str(game_pk),
        "home": _side_evidence(game, feed, box, "home"),
        "away": _side_evidence(game, feed, box, "away"),
        "policy": "schedule+feed consensus required LATE; schedule+feed+official boxscore conflict blocks FINAL",
    }


def validate_starters_for_phase(game: dict[str, Any], phase: str, *, getter: MLBGetter = http_json) -> dict[str, Any]:
    phase = str(phase or "EARLY").upper()
    evidence = starter_integrity_evidence(game, getter=getter)
    if phase == "EARLY":
        evidence["eligible"] = True
        evidence["reason"] = "EARLY allows provisional starter identity"
        return evidence

    failures: list[str] = []
    for side in ("away", "home"):
        row = evidence[side]
        sources = {src["source"]: src for src in row["sources"]}
        schedule = sources["schedule.probablePitcher"]
        feed = sources["feed.gameData.probablePitchers"]
        box = sources["boxscore.pitchers[0]"]

        if not schedule.get("available") or not feed.get("available"):
            failures.append(f"{side}:starter_not_confirmed_by_schedule_and_feed")
            continue
        if str(schedule.get("id")) != str(feed.get("id")):
            failures.append(
                f"{side}:STARTER_CONFLICT schedule={schedule.get('name') or schedule.get('id')} "
                f"feed={feed.get('name') or feed.get('id')}"
            )
            continue
        if box.get("available") and str(box.get("id")) != str(schedule.get("id")):
            failures.append(
                f"{side}:STARTER_CONFLICT schedule={schedule.get('name') or schedule.get('id')} "
                f"boxscore={box.get('name') or box.get('id')}"
            )

    evidence["eligible"] = not failures
    evidence["failures"] = failures
    if failures:
        raise ValueError("; ".join(failures))
    return evidence
