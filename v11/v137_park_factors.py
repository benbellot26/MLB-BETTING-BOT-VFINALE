from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import core
from . import predictive_v124 as v124
from .v124_statcast_provider import _TableParser, _norm_header
from .v137_free_data import COHORT

OUT = Path("data/v137_park_factors.json")
REPORT = Path("data/v137_park_factors_report.json")
SOURCE_URL = "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"
MLB_FALLBACK_PROVIDER = "MLB Stats API completed-season venue run environment"
MIN_FALLBACK_VENUE_GAMES = 20
SAVANT_ROLLING_SEASONS = 3

_SEASON_GAMES_CACHE: dict[int, list[dict[str, Any]]] = {}
_MLB_FALLBACK_CACHE: dict[int, list[dict[str, Any]]] = {}


def _num(value: Any) -> float | None:
    try:
        out = float(str(value).replace(",", "").strip())
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _pick(row: dict[str, Any], *aliases: str) -> Any:
    normalized = {_norm(k): v for k, v in row.items()}
    for alias in aliases:
        key = _norm(alias)
        if key in normalized and normalized[key] not in (None, ""):
            return normalized[key]
    return None


def _normalize_park_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    venue = str(_pick(raw, "venue_name", "venue", "venueName") or "").replace("Image", "").strip()
    team = str(_pick(raw, "team_name", "team", "teamName") or "").replace("Image", "").strip()
    park = _num(_pick(raw, "index_woba", "index_wOBA", "park_factor", "parkfactor"))
    if not venue or park is None:
        return None
    return {
        "team": team or None,
        "venue": venue,
        "venue_id": _pick(raw, "venue_id", "venueId"),
        "year_label": _pick(raw, "year", "year_label", "yearLabel"),
        "park_factor_index": park,
        "woba_contact_index": _num(_pick(raw, "index_wobacon", "wobacon", "index_woba_con")),
        "xwoba_contact_index": _num(_pick(raw, "index_xwobacon", "xwobacon", "index_xwoba_con")),
        "hard_hit_index": _num(_pick(raw, "index_hardhit", "hardhit", "index_hard_hit")),
        "runs_index": _num(_pick(raw, "index_r", "index_runs", "runs", "r")),
        "hr_index": _num(_pick(raw, "index_hr", "hr")),
        "pa": _num(_pick(raw, "pa", "plate_appearances", "plateappearances")),
        "source_method": "Baseball Savant Statcast Park Factors",
        "handedness_specific": True,
    }


def _parse_park_table(html: str) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(html or "")
    for table in parser.tables:
        if not table:
            continue
        header = [text for tag, text in table[0] if tag == "th"]
        if not header:
            header = [text for _, text in table[0]]
        normalized = [_norm_header(x) for x in header]
        if "venue" not in normalized and "venuename" not in normalized:
            continue
        out: list[dict[str, Any]] = []
        for raw in table[1:]:
            vals = [text for _, text in raw]
            if len(vals) < len(header):
                continue
            item = _normalize_park_record({normalized[i]: vals[i] for i in range(min(len(normalized), len(vals)))})
            if item:
                out.append(item)
        if out:
            return out
    return []


def _embedded_json_lists(html: str) -> list[list[dict[str, Any]]]:
    """Extract Savant's client-side ``data = [...]`` payload when it is present."""
    decoder = json.JSONDecoder()
    candidates: list[list[dict[str, Any]]] = []
    for match in re.finditer(r"\bdata\s*=\s*", html or "", flags=re.IGNORECASE):
        tail = (html or "")[match.end():].lstrip()
        if not tail.startswith("["):
            continue
        try:
            value, _ = decoder.raw_decode(tail)
        except Exception:
            continue
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            candidates.append(value)
    return candidates


def _parse_embedded_park_data(html: str) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    for candidate in _embedded_json_lists(html):
        rows = []
        for raw in candidate:
            item = _normalize_park_record(raw)
            if item:
                rows.append(item)
        if len(rows) > len(best):
            best = rows
    return best


def _parse_park_payload(html: str) -> tuple[list[dict[str, Any]], str]:
    embedded = _parse_embedded_park_data(html)
    if embedded:
        return embedded, "embedded_json"
    table = _parse_park_table(html)
    if table:
        return table, "html_table"
    return [], "none"


def _date_chunks(start: date, end: date, days: int = 31):
    current = start
    while current <= end:
        stop = min(end, current + timedelta(days=days - 1))
        yield current, stop
        current = stop + timedelta(days=1)


def _fetch_completed_season_games(season: int) -> list[dict[str, Any]]:
    """Fetch final regular-season games for a completed source season once."""
    season = int(season)
    if season in _SEASON_GAMES_CACHE:
        return _SEASON_GAMES_CACHE[season]

    games: dict[str, dict[str, Any]] = {}
    start = date(season, 3, 1)
    end = date(season, 11, 30)
    for a, b in _date_chunks(start, end):
        payload = core.mlb(
            "v1/schedule",
            {
                "sportId": 1,
                "startDate": a.isoformat(),
                "endDate": b.isoformat(),
                "gameTypes": "R",
                "hydrate": "venue",
            },
        ) or {}
        for day in payload.get("dates") or []:
            for game in day.get("games") or []:
                status = game.get("status") or {}
                final = (
                    str(status.get("abstractGameState") or "").lower() == "final"
                    or str(status.get("codedGameState") or "").upper() == "F"
                )
                gid = str(game.get("gamePk") or "")
                if final and gid:
                    games[gid] = game
    out = sorted(games.values(), key=lambda game: str(game.get("gameDate") or ""))
    _SEASON_GAMES_CACHE[season] = out
    return out


def _mlb_fallback_rows(target_season: int) -> list[dict[str, Any]]:
    """Derive a robust descriptive venue run factor from prior completed seasons.

    This is intentionally a fallback, not a replacement claim for Savant's
    player-controlled park model. It prevents a client-rendering change on the
    Savant page from collapsing historical park coverage to zero. The factor is
    computed only from the three seasons ending before ``target_season``.
    """
    target = int(target_season)
    if target in _MLB_FALLBACK_CACHE:
        return _MLB_FALLBACK_CACHE[target]

    source_years = [target - 3, target - 2, target - 1]
    venue_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"runs": 0.0, "games": 0, "venue_id": None, "teams": Counter()}
    )
    league_runs = 0.0
    league_games = 0

    for season in source_years:
        for game in _fetch_completed_season_games(season):
            teams = game.get("teams") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}
            home_score = _num(home.get("score"))
            away_score = _num(away.get("score"))
            venue = game.get("venue") or {}
            venue_name = str(venue.get("name") or "").strip()
            if home_score is None or away_score is None or not venue_name:
                continue
            total_runs = home_score + away_score
            league_runs += total_runs
            league_games += 1
            stat = venue_stats[venue_name]
            stat["runs"] += total_runs
            stat["games"] += 1
            stat["venue_id"] = venue.get("id") or stat.get("venue_id")
            home_team = str(((home.get("team") or {}).get("name")) or "")
            if home_team:
                stat["teams"][home_team] += 1

    if league_games <= 0:
        _MLB_FALLBACK_CACHE[target] = []
        return []

    league_runs_per_game = league_runs / league_games
    rows: list[dict[str, Any]] = []
    for venue_name, stat in venue_stats.items():
        games = int(stat["games"])
        if games < MIN_FALLBACK_VENUE_GAMES:
            continue
        venue_rpg = float(stat["runs"]) / games
        raw_index = 100.0 * venue_rpg / max(0.1, league_runs_per_game)
        index = max(75.0, min(135.0, raw_index))
        team = stat["teams"].most_common(1)[0][0] if stat["teams"] else None
        rows.append(
            {
                "team": team,
                "venue": venue_name,
                "venue_id": stat.get("venue_id"),
                "year_label": f"{source_years[0]}-{source_years[-1]}",
                "park_factor_index": index,
                "woba_contact_index": None,
                "xwoba_contact_index": None,
                "hard_hit_index": None,
                "runs_index": index,
                "hr_index": None,
                "pa": None,
                "games": games,
                "venue_runs_per_game": venue_rpg,
                "league_runs_per_game": league_runs_per_game,
                "source_method": "venue total runs per game divided by MLB total runs per game",
                "handedness_specific": False,
            }
        )
    rows.sort(key=lambda row: str(row.get("venue") or ""))
    _MLB_FALLBACK_CACHE[target] = rows
    return rows


def fetch_prior_factors(
    target_season: int,
    bat_side: str = "",
    fetch_text: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Fetch a three-season Savant park-factor window ending before target season.

    If Savant's client-rendered leaderboard no longer embeds a parseable payload,
    use a leakage-safe MLB Stats API venue run-environment fallback rather than
    silently returning zero park coverage.
    """
    target = int(target_season)
    source_end = target - 1
    source_years = [source_end - 2, source_end - 1, source_end]
    side = str(bat_side or "").upper()
    if side not in {"", "L", "R"}:
        raise ValueError("bat_side must be '', 'L', or 'R'")
    fetch_text = fetch_text or v124._http_text
    params = {
        "batSide": side,
        "condition": "All",
        "parks": "mlb",
        "rolling": SAVANT_ROLLING_SEASONS,
        "stat": "index_wOBA",
        "type": "year",
        "year": source_end,
    }
    html = fetch_text(SOURCE_URL, params, timeout=30)
    rows, parse_mode = _parse_park_payload(html or "")
    provider = "Baseball Savant Statcast Park Factors"
    fallback = False
    if not rows:
        rows = [dict(row) for row in _mlb_fallback_rows(target)]
        parse_mode = "mlb_stats_derived" if rows else "none"
        provider = MLB_FALLBACK_PROVIDER if rows else provider
        fallback = bool(rows)
    else:
        for row in rows:
            row["handedness_specific"] = bool(side)

    return {
        "schema": "v13-7-prior-park-factor-v5",
        "cohort": COHORT,
        "target_season": target,
        "source_window_end_season": source_end,
        "source_window_years": source_years,
        "savant_rolling_seasons": SAVANT_ROLLING_SEASONS,
        "bat_side": side or "ALL",
        "point_in_time": True,
        "native_live": False,
        "promotion_eligible": False,
        "provider": provider,
        "source_url": SOURCE_URL if not fallback else "https://statsapi.mlb.com/api/v1/schedule",
        "parse_mode": parse_mode,
        "provider_fallback": fallback,
        "handedness_specific": bool(side) and not fallback,
        "rows": rows,
        "venue_count": len(rows),
        "request_contract": {"rolling": SAVANT_ROLLING_SEASONS, "year": source_end},
        "policy": "exactly three completed seasons ending before target season; target-season results excluded",
    }


def collect(start_season: int, end_season: int) -> tuple[dict[str, Any], dict[str, Any]]:
    start, end = int(start_season), int(end_season)
    if end < start:
        raise ValueError("end season before start season")
    seasons: dict[str, Any] = {}
    failures = []
    empty_parses = []
    parse_modes: dict[str, dict[str, str]] = {}
    fallback_requests = 0
    for season in range(start, end + 1):
        side_payloads = {}
        parse_modes[str(season)] = {}
        for side in ("", "L", "R"):
            label = side or "ALL"
            try:
                payload = fetch_prior_factors(season, side)
                side_payloads[label] = payload
                parse_modes[str(season)][label] = str(payload.get("parse_mode") or "none")
                fallback_requests += int(bool(payload.get("provider_fallback")))
                if int(payload.get("venue_count") or 0) == 0:
                    empty_parses.append({"season": season, "bat_side": label, "error": "empty_parse"})
            except Exception as exc:
                side_payloads[label] = {
                    "schema": "v13-7-prior-park-factor-v5",
                    "target_season": season,
                    "bat_side": label,
                    "point_in_time": True,
                    "rows": [],
                    "venue_count": 0,
                    "parse_mode": "error",
                    "error": f"{type(exc).__name__}:{exc}",
                }
                parse_modes[str(season)][label] = "error"
                failures.append({"season": season, "bat_side": label, "error": type(exc).__name__})
        seasons[str(season)] = side_payloads
    artifact = {
        "schema": "v13-7-prior-park-factors-store-v5",
        "cohort": COHORT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "point_in_time_policy": True,
        "native_live": False,
        "promotion_eligible": False,
        "savant_rolling_seasons": SAVANT_ROLLING_SEASONS,
        "seasons": seasons,
    }
    venue_counts = {
        season: {side: int(payload.get("venue_count") or 0) for side, payload in sides.items()}
        for season, sides in seasons.items()
    }
    report = {
        "schema": "v13-7-prior-park-factors-report-v5",
        "start_season": start,
        "end_season": end,
        "season_count": len(seasons),
        "requests_expected": len(seasons) * 3,
        "failures": failures,
        "failed_requests": len(failures),
        "empty_parses": empty_parses,
        "empty_parse_count": len(empty_parses),
        "fallback_requests": fallback_requests,
        "parse_modes": parse_modes,
        "venue_counts": venue_counts,
        "total_venue_rows": sum(sum(sides.values()) for sides in venue_counts.values()),
        "rolling_parameter": SAVANT_ROLLING_SEASONS,
        "rolling_contract": "Baseball Savant 3-year rolling window",
        "fallback_policy": "Savant first; prior completed-season MLB venue run environment if client-rendered Savant payload is unavailable",
        "promotion_eligible": False,
    }
    return artifact, report


def load(path: Path = OUT) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def venue_prior(artifact: dict[str, Any], target_season: int, venue: str) -> dict[str, Any]:
    sides = (((artifact or {}).get("seasons") or {}).get(str(int(target_season))) or {})
    result = {
        "available": False,
        "target_season": int(target_season),
        "venue": venue,
        "point_in_time": True,
        "provider": "Baseball Savant / MLB Stats prior park factor",
    }
    key = _norm(venue)
    for side in ("ALL", "L", "R"):
        payload = sides.get(side) or {}
        row = next((r for r in payload.get("rows") or [] if _norm(r.get("venue")) == key), None)
        if row:
            result[side.lower()] = row
            result["source_window_end_season"] = payload.get("source_window_end_season")
            result["source_window_years"] = payload.get("source_window_years")
            result["savant_rolling_seasons"] = payload.get("savant_rolling_seasons")
            result["provider_fallback"] = bool(payload.get("provider_fallback"))
            result["handedness_specific"] = bool(payload.get("handedness_specific"))
    result["available"] = any(k in result for k in ("all", "l", "r"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect leakage-safe prior-season park factors")
    parser.add_argument("--start-season", type=int, default=2021)
    parser.add_argument("--end-season", type=int, default=date.today().year)
    args = parser.parse_args()
    artifact, report = collect(args.start_season, args.end_season)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if int(report.get("failed_requests") or 0):
        raise SystemExit(f"Park-factor provider failure: {report['failed_requests']} request(s) failed")
    if int(report.get("total_venue_rows") or 0) == 0:
        raise SystemExit("Park-factor provider failure: zero parsed venue rows")


if __name__ == "__main__":
    main()
