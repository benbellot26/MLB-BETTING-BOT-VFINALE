from __future__ import annotations

"""Native point-in-time acquisition primitives for Pulsar V14."""

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
MATCH_TIME_TOLERANCE_MINUTES = 150.0

JsonGetter = Callable[[str, dict[str, Any]], Any]
_HTTP_CACHE: dict[str, Any] = {}


def clear_http_cache() -> None:
    _HTTP_CACHE.clear()


def resolve_target_date(*, now: datetime | None = None, override: str | None = None) -> str:
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


def _cache_key(url: str, params: dict[str, Any]) -> str:
    return f"{url}?{urlencode(sorted((str(k), str(v)) for k, v in params.items()), safe=',')}"


def http_json(url: str, params: dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT, retries: int = 2, use_cache: bool = True) -> Any:
    key = _cache_key(url, params)
    if use_cache and key in _HTTP_CACHE:
        return _HTTP_CACHE[key]
    query = urlencode(params, safe=",")
    target = f"{url}?{query}" if query else url
    request = Request(target, headers={"User-Agent": "Pulsar-V14", "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                payload = json.loads(body) if body else None
                if use_cache:
                    _HTTP_CACHE[key] = payload
                return payload
        except HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                wait = max(0.5, float(retry_after)) if retry_after else 1.2 * (attempt + 1)
            except Exception:
                wait = 1.2 * (attempt + 1)
            time.sleep(wait)
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


def odds_snapshot(*, api_key: str | None = None, getter: JsonGetter = http_json, bookmakers: tuple[str, ...] = DEFAULT_BOOKMAKERS) -> list[dict[str, Any]]:
    key = (api_key if api_key is not None else os.getenv("ODDS_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("ODDS_API_KEY absente")
    payload = getter(ODDS_URL, {
        "apiKey": key,
        "regions": "eu",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
        "bookmakers": ",".join(bookmakers),
    }) or []
    if not isinstance(payload, list):
        raise ValueError("Odds API payload must be a list")
    return [event for event in payload if isinstance(event, dict)]


TEAM_ALIASES = {
    "oaklandathletics": "athletics",
    "sacramentoathletics": "athletics",
    "athletics": "athletics",
}


def canonical_team_name(value: Any) -> str:
    normalized = norm_name(value)
    return TEAM_ALIASES.get(normalized, normalized)


def _team_pair(obj: dict[str, Any], *, mlb: bool) -> tuple[str, str]:
    if mlb:
        teams = obj.get("teams") or {}
        home = ((teams.get("home") or {}).get("team") or {}).get("name")
        away = ((teams.get("away") or {}).get("team") or {}).get("name")
    else:
        home, away = obj.get("home_team"), obj.get("away_team")
    return canonical_team_name(home), canonical_team_name(away)


def match_events(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Match MLB games to unique Odds events by teams and start time.

    Team-only matching is unsafe for doubleheaders. Events are consumed at most
    once and a timed match must be within MATCH_TIME_TOLERANCE_MINUTES. If event
    timestamps are missing, fallback is allowed only for an unambiguous 1:1 pair.
    """
    by_pair_games: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_pair_events: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for game in games:
        pair = _team_pair(game, mlb=True)
        if all(pair):
            by_pair_games.setdefault(pair, []).append(game)
    for event in events:
        pair = _team_pair(event, mlb=False)
        if all(pair):
            by_pair_events.setdefault(pair, []).append(event)

    matched: dict[str, dict[str, Any]] = {}
    for pair, pair_games in by_pair_games.items():
        pair_events = list(by_pair_events.get(pair) or [])
        if not pair_events:
            continue
        if len(pair_games) == 1 and len(pair_events) == 1:
            game, event = pair_games[0], pair_events[0]
            gid = game.get("gamePk")
            if gid is None:
                continue
            try:
                delta = abs((parse_time(game.get("gameDate")) - parse_time(event.get("commence_time"))).total_seconds()) / 60.0
                if delta > MATCH_TIME_TOLERANCE_MINUTES:
                    continue
            except Exception:
                pass
            matched[str(gid)] = event
            continue

        available = list(pair_events)
        for game in sorted(pair_games, key=lambda g: str(g.get("gameDate") or "")):
            gid = game.get("gamePk")
            if gid is None:
                continue
            try:
                game_dt = parse_time(game.get("gameDate"))
            except Exception:
                continue
            timed: list[tuple[float, int, dict[str, Any]]] = []
            for idx, event in enumerate(available):
                try:
                    event_dt = parse_time(event.get("commence_time"))
                except Exception:
                    continue
                delta = abs((game_dt - event_dt).total_seconds()) / 60.0
                timed.append((delta, idx, event))
            if not timed:
                continue
            delta, idx, event = min(timed, key=lambda item: item[0])
            if delta <= MATCH_TIME_TOLERANCE_MINUTES:
                matched[str(gid)] = event
                available.pop(idx)
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
            "schema": "pulsar-v14-pregame-snapshot-v2",
            "target_date": self.target_date,
            "analyzed_at": self.analyzed_at,
            "games": self.games,
            "events": self.events,
            "matched_game_pks": sorted(self.matches),
            "market_probability_used_as_feature": False,
        }


def collect_pregame(target_date: str, *, analyzed_at: str | None = None, api_key: str | None = None, schedule_getter: JsonGetter = http_json, odds_getter: JsonGetter = http_json) -> PregameSnapshot:
    clear_http_cache()
    at = analyzed_at or datetime.now(timezone.utc).isoformat()
    games = future_games(mlb_schedule(target_date, getter=schedule_getter), as_of=at)
    events = odds_snapshot(api_key=api_key, getter=odds_getter)
    matches = match_events(games, events)
    return PregameSnapshot(
        target_date=str(target_date), analyzed_at=str(at), games=games, events=events, matches=matches,
    ).validated()
