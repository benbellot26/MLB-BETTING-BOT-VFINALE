from __future__ import annotations

"""Native point-in-time acquisition primitives for Pulsar V14.

Only public MLB schedule data and bookmaker market snapshots are acquired here.
No probability is computed and no market probability is converted into a model
feature. The functions are intentionally small and injectable for deterministic
tests/replays.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
PARIS = ZoneInfo("Europe/Paris")
DEFAULT_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "25") or 25)
DEFAULT_BOOKMAKERS = tuple(
    x.strip()
    for x in os.getenv(
        "ODDS_BOOKMAKERS",
        "winamax_fr,pinnacle,betfair_ex_eu,matchbook,betonlineag,betclic_fr,unibet_fr,pmu_fr,netbet_fr",
    ).split(",")
    if x.strip()
)

JsonGetter = Callable[[str, dict[str, Any]], Any]


def resolve_target_date(*, now: datetime | None = None, override: str | None = None) -> str:
    """Resolve the MLB slate date using the historical production convention.

    The slate follows Europe/Paris. Before 06:00 local time it remains attached
    to the previous calendar date so late US games are not accidentally shifted
    into the next slate. MLB_DATE, or the explicit override, wins when supplied.
    """
    explicit = override if override is not None else os.getenv("MLB_DATE")
    if explicit:
        value = str(explicit).strip()
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("MLB_DATE must use YYYY-MM-DD") from exc
        return value

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(PARIS)
    day = local.date() - timedelta(days=1) if local.hour < 6 else local.date()
    return day.isoformat()


def norm_name(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def parse_time(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def http_json(url: str, params: dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT, retries: int = 2) -> Any:
    query = urlencode(params, safe=",")
    target = f"{url}?{query}" if query else url
    request = Request(target, headers={"User-Agent": "Pulsar-V14", "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return json.loads(body) if body else None
        except HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise
            time.sleep(1.2 * (attempt + 1))
        except Exception as exc:
            last = exc
            if attempt >= retries:
                raise
            time.sleep(1.0 + attempt)
    if last is not None:
        raise last
    raise RuntimeError("HTTP request failed without exception")


def mlb_schedule(day: str, *, getter: JsonGetter = http_json, hydrate: str = "probablePitcher,linescore") -> list[dict[str, Any]]:
    payload = getter(MLB_SCHEDULE_URL, {"sportId": 1, "date": str(day), "hydrate": hydrate}) or {}
    return [game for block in payload.get("dates") or [] for game in block.get("games") or [] if isinstance(game, dict)]


def odds_snapshot(
    *,
    api_key: str | None = None,
    getter: JsonGetter = http_json,
    bookmakers: tuple[str, ...] = DEFAULT_BOOKMAKERS,
) -> list[dict[str, Any]]:
    key = (api_key if api_key is not None else os.getenv("ODDS_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("ODDS_API_KEY absente")
    payload = getter(
        ODDS_URL,
        {
            "apiKey": key,
            "regions": "eu",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "bookmakers": ",".join(bookmakers),
        },
    ) or []
    if not isinstance(payload, list):
        raise ValueError("Odds API payload must be a list")
    return [event for event in payload if isinstance(event, dict)]


def match_events(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        key = (norm_name(event.get("home_team")), norm_name(event.get("away_team")))
        if all(key):
            index[key] = event

    matched: dict[str, dict[str, Any]] = {}
    for game in games:
        teams = game.get("teams") or {}
        home = ((teams.get("home") or {}).get("team") or {}).get("name")
        away = ((teams.get("away") or {}).get("team") or {}).get("name")
        event = index.get((norm_name(home), norm_name(away)))
        game_pk = game.get("gamePk")
        if event is not None and game_pk is not None:
            matched[str(game_pk)] = event
    return matched


def future_games(games: list[dict[str, Any]], *, as_of: Any) -> list[dict[str, Any]]:
    cutoff = parse_time(as_of)
    out = []
    for game in games:
        try:
            game_time = parse_time(game.get("gameDate"))
        except Exception:
            continue
        if game_time > cutoff:
            out.append(game)
    return out


@dataclass(frozen=True)
class PregameSnapshot:
    target_date: str
    analyzed_at: str
    games: list[dict[str, Any]]
    events: list[dict[str, Any]]
    matches: dict[str, dict[str, Any]]

    def validated(self) -> "PregameSnapshot":
        parse_time(self.analyzed_at)
        if not self.target_date:
            raise ValueError("target_date is required")
        for game in self.games:
            if not isinstance(game, dict):
                raise ValueError("games must contain objects")
        for event in self.events:
            if not isinstance(event, dict):
                raise ValueError("events must contain objects")
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "pulsar-v14-pregame-snapshot-v1",
            "target_date": self.target_date,
            "analyzed_at": self.analyzed_at,
            "games": self.games,
            "events": self.events,
            "matched_game_pks": sorted(self.matches),
            "market_probability_used_as_feature": False,
        }


def collect_pregame(
    target_date: str,
    *,
    analyzed_at: str | None = None,
    api_key: str | None = None,
    schedule_getter: JsonGetter = http_json,
    odds_getter: JsonGetter = http_json,
) -> PregameSnapshot:
    at = analyzed_at or datetime.now(timezone.utc).isoformat()
    games = future_games(mlb_schedule(target_date, getter=schedule_getter), as_of=at)
    events = odds_snapshot(api_key=api_key, getter=odds_getter)
    matches = match_events(games, events)
    return PregameSnapshot(
        target_date=str(target_date),
        analyzed_at=str(at),
        games=games,
        events=events,
        matches=matches,
    ).validated()
