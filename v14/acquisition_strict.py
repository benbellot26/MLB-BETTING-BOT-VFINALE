from __future__ import annotations

"""Stricter V14 event matching without changing the legacy acquisition contract."""

from datetime import datetime, timezone
from typing import Any

from .acquisition import PregameSnapshot, canonical_team_name, clear_http_cache, future_games, mlb_schedule, odds_snapshot, parse_time

MATCH_TIME_TOLERANCE_MINUTES = 90.0
AMBIGUITY_GAP_MINUTES = 30.0


def _pair(obj: dict[str, Any], *, mlb: bool) -> tuple[str, str]:
    if mlb:
        teams = obj.get("teams") or {}
        home = ((teams.get("home") or {}).get("team") or {}).get("name")
        away = ((teams.get("away") or {}).get("team") or {}).get("name")
    else:
        home, away = obj.get("home_team"), obj.get("away_team")
    return canonical_team_name(home), canonical_team_name(away)


def _delta(game: dict[str, Any], event: dict[str, Any]) -> float | None:
    try:
        return abs((parse_time(game.get("gameDate")) - parse_time(event.get("commence_time"))).total_seconds()) / 60.0
    except Exception:
        return None


def match_events_strict(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One-to-one team/time matcher that fails closed on doubleheader ambiguity."""
    by_games: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for game in games:
        pair = _pair(game, mlb=True)
        if all(pair): by_games.setdefault(pair, []).append(game)
    for event in events:
        pair = _pair(event, mlb=False)
        if all(pair): by_events.setdefault(pair, []).append(event)

    matched: dict[str, dict[str, Any]] = {}
    for pair, pair_games in by_games.items():
        available = list(by_events.get(pair) or [])
        if not available: continue
        if len(pair_games) == 1 and len(available) == 1:
            gid = pair_games[0].get("gamePk")
            if gid is None: continue
            d = _delta(pair_games[0], available[0])
            # Missing event time is acceptable only for a genuinely unambiguous 1:1 pair.
            if d is None or d <= MATCH_TIME_TOLERANCE_MINUTES:
                matched[str(gid)] = available[0]
            continue

        for game in sorted(pair_games, key=lambda g: str(g.get("gameDate") or "")):
            gid = game.get("gamePk")
            if gid is None: continue
            candidates = sorted((d, i, event) for i, event in enumerate(available) if (d := _delta(game, event)) is not None)
            if not candidates: continue
            best = candidates[0]
            if best[0] > MATCH_TIME_TOLERANCE_MINUTES: continue
            # Two nearly-equidistant events are unsafe: do not guess which half of a DH it is.
            if len(candidates) > 1 and abs(candidates[1][0] - best[0]) < AMBIGUITY_GAP_MINUTES:
                continue
            matched[str(gid)] = best[2]
            available.pop(best[1])
    return matched


def collect_pregame_strict(target_date: str, *, analyzed_at: str | None = None, api_key: str | None = None, schedule_getter=None, odds_getter=None) -> PregameSnapshot:
    clear_http_cache()
    at = analyzed_at or datetime.now(timezone.utc).isoformat()
    schedule_kwargs = {"getter": schedule_getter} if schedule_getter is not None else {}
    odds_kwargs = {"getter": odds_getter} if odds_getter is not None else {}
    games = future_games(mlb_schedule(target_date, **schedule_kwargs), as_of=at)
    events = odds_snapshot(api_key=api_key, **odds_kwargs)
    matches = match_events_strict(games, events)
    return PregameSnapshot(target_date=str(target_date), analyzed_at=str(at), games=games, events=events, matches=matches).validated()
