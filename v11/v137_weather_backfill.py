from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import core
from .v137_free_data import (
    COHORT,
    DEFAULT_WEATHER_PUBLICATION_LAG_HOURS,
    WEATHER_ARCHIVE_START,
    historical_weather_for_game,
)
from .v137_team_history import fetch_schedule_span

OUT_DIR = Path("data/v137")
REPORT = Path("data/v137_weather_backfill_report.json")
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_MAX_DAYS = 7
PREVIOUS_RUNS_BASE_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)


def _is_regular_game(game: dict[str, Any]) -> bool:
    return str(game.get("gameType") or "R").upper() == "R"


def _team_name(game: dict[str, Any], side: str) -> str:
    return str(((((game.get("teams") or {}).get(side) or {}).get("team") or {}).get("name")) or "")


def _utc(value: Any) -> datetime:
    dt = value if isinstance(value, datetime) else core.parse_dt(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _previous_day_offset(game_time: Any, as_of: Any) -> int | None:
    """Choose a fixed-lead archive that is conservatively public by ``as_of``.

    Open-Meteo previous_dayN values represent forecasts made N*24 hours before
    valid time. Add the same conservative six-hour publication margin used by
    the Single Runs path before selecting the minimum safe offset.
    """
    game_dt = _utc(game_time)
    asof_dt = _utc(as_of)
    hours_before_game = max(0.0, (game_dt - asof_dt).total_seconds() / 3600.0)
    safe_hours = hours_before_game + DEFAULT_WEATHER_PUBLICATION_LAG_HOURS
    offset = max(1, int(math.ceil(safe_hours / 24.0)))
    return offset if offset <= PREVIOUS_RUNS_MAX_DAYS else None


def _hourly_value(hourly: dict[str, Any], key: str, idx: int) -> Any:
    values = hourly.get(key) or []
    return values[idx] if idx < len(values) else None


def previous_run_weather_for_game(
    game_time: Any,
    home_name: str,
    as_of: Any,
    fetch_json=None,
) -> dict[str, Any]:
    """PIT-safe fallback using Open-Meteo fixed-lead previous-run forecasts.

    This fallback is used only when the exact Single Runs archive path is
    unavailable. It deliberately chooses a forecast older than ``as_of`` and
    remains reconstructed/non-promotion evidence.
    """
    game_dt = _utc(game_time)
    asof_dt = _utc(as_of)
    if asof_dt >= game_dt:
        return {"available": False, "point_in_time": False, "reason": "analysis_not_pregame"}

    coord = core.COORD.get(home_name)
    if not coord:
        return {"available": False, "point_in_time": True, "reason": "park_coordinates_missing"}

    offset = _previous_day_offset(game_dt, asof_dt)
    if offset is None:
        return {
            "available": False,
            "point_in_time": True,
            "reason": "previous_runs_safe_offset_exceeds_archive_horizon",
        }

    suffix = f"_previous_day{offset}"
    requested = [f"{name}{suffix}" for name in PREVIOUS_RUNS_BASE_VARIABLES]
    params = {
        "latitude": coord[0],
        "longitude": coord[1],
        "timezone": "UTC",
        "hourly": ",".join(requested),
        "models": "ecmwf_ifs",
        "start_date": game_dt.date().isoformat(),
        "end_date": game_dt.date().isoformat(),
    }
    fetch_json = fetch_json or core.http_json
    try:
        payload = fetch_json(PREVIOUS_RUNS_URL, params) or {}
    except Exception as exc:
        return {
            "available": False,
            "point_in_time": True,
            "reason": f"previous_runs_error:{type(exc).__name__}",
            "previous_day_offset": offset,
        }

    hourly = payload.get("hourly") or {}
    raw_times = hourly.get("time") or []
    if not raw_times:
        return {
            "available": False,
            "point_in_time": True,
            "reason": "previous_runs_hourly_missing",
            "previous_day_offset": offset,
        }

    parsed = []
    for value in raw_times:
        dt = datetime.fromisoformat(str(value))
        parsed.append(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc))
    idx = min(range(len(parsed)), key=lambda i: abs((parsed[i] - game_dt).total_seconds()))
    if abs((parsed[idx] - game_dt).total_seconds()) > 90 * 60:
        return {
            "available": False,
            "point_in_time": True,
            "reason": "previous_runs_does_not_cover_game_hour",
            "previous_day_offset": offset,
        }

    def value(name: str) -> Any:
        return _hourly_value(hourly, f"{name}{suffix}", idx)

    return {
        "available": True,
        "point_in_time": True,
        "cohort": COHORT,
        "provider": "Open-Meteo Previous Runs / ECMWF IFS",
        "provider_fallback": True,
        "previous_day_offset": offset,
        "forecast_lead_hours": offset * 24,
        "assumed_publication_lag_hours": DEFAULT_WEATHER_PUBLICATION_LAG_HOURS,
        "as_of": asof_dt.isoformat(),
        "valid_hour": parsed[idx].isoformat(),
        "temperature_c": core.num(value("temperature_2m"), None),
        "humidity_pct": core.num(value("relative_humidity_2m"), None),
        "dew_point_c": core.num(value("dew_point_2m"), None),
        "surface_pressure_hpa": core.num(value("surface_pressure"), None),
        "precipitation_mm": core.num(value("precipitation"), None),
        "precip_probability": None,
        "cloud_cover_pct": core.num(value("cloud_cover"), None),
        "wind_kph": core.num(value("wind_speed_10m"), None),
        "wind_direction_deg": core.num(value("wind_direction_10m"), None),
        "wind_gust_kph": core.num(value("wind_gusts_10m"), None),
        "request_model": "ecmwf_ifs",
    }


def collect(start: str, end: str, lead_hours: int = 2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    games = fetch_schedule_span(start, end)
    rows = []
    status_counts = defaultdict(int)
    provider_counts = defaultdict(int)
    for game in games:
        if not _is_regular_game(game):
            continue
        gid = game.get("gamePk")
        home = _team_name(game, "home")
        away = _team_name(game, "away")
        try:
            game_dt = core.parse_dt(game.get("gameDate"))
            if game_dt.tzinfo is None:
                game_dt = game_dt.replace(tzinfo=timezone.utc)
            game_dt = game_dt.astimezone(timezone.utc)
        except Exception:
            status_counts["bad_game_time"] += 1
            continue
        as_of = game_dt - timedelta(hours=max(1, int(lead_hours)))
        weather = historical_weather_for_game(game_dt, home, as_of)
        if not weather.get("available") and str(weather.get("reason") or "").startswith("single_run"):
            weather = previous_run_weather_for_game(game_dt, home, as_of)

        if weather.get("available"):
            provider = str(weather.get("provider") or "unknown")
            provider_counts[provider] += 1
            status_counts["available"] += 1
        else:
            status_counts[str(weather.get("reason") or "unavailable")] += 1

        rows.append(
            {
                "schema": "v13-7-free-weather-feature-v1",
                "cohort": COHORT,
                "native_live": False,
                "promotion_eligible": False,
                "game_pk": gid,
                "game_date": game_dt.isoformat(),
                "as_of": as_of.isoformat(),
                "home": home,
                "away": away,
                "weather": weather,
                "target_labels_embedded": False,
                "market_data_embedded": False,
            }
        )
    report = {
        "schema": "v13-7-free-weather-backfill-report-v2",
        "cohort": COHORT,
        "start": start,
        "end": end,
        "lead_hours": int(lead_hours),
        "archive_available_from": WEATHER_ARCHIVE_START.isoformat(),
        "rows": len(rows),
        "available_rows": sum(bool((r.get("weather") or {}).get("available")) for r in rows),
        "point_in_time_rows": sum(bool((r.get("weather") or {}).get("point_in_time")) for r in rows),
        "status_counts": dict(sorted(status_counts.items())),
        "provider_counts": dict(sorted(provider_counts.items())),
        "fallback_policy": "Single Runs first; Previous Runs fixed lead selected conservatively when exact run is unavailable",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promotion_eligible": False,
    }
    return rows, report


def _month_key(row: dict[str, Any]) -> str:
    return str(row.get("game_date") or "")[:7]


def write(rows: list[dict[str, Any]]) -> list[str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_month_key(row)].append(row)
    paths = []
    for month, items in sorted(grouped.items()):
        path = OUT_DIR / f"weather_{month}.jsonl.gz"
        merged: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        key = str(row.get("game_pk") or "") + "|" + str(row.get("as_of") or "")
                        merged[key] = row
            except Exception:
                merged = {}
        for row in items:
            key = str(row.get("game_pk") or "") + "|" + str(row.get("as_of") or "")
            merged[key] = row
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
            for row in sorted(merged.values(), key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or ""))):
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        paths.append(str(path))
    return paths


def main() -> None:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(description="Backfill free point-in-time archived weather for MLB games")
    parser.add_argument("--start", default=yesterday.isoformat())
    parser.add_argument("--end", default=yesterday.isoformat())
    parser.add_argument("--lead-hours", type=int, default=2)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    rows, report = collect(args.start, args.end, args.lead_hours)
    report["files"] = write(rows) if args.persist else []
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
