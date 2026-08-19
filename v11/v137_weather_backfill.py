from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import core
from .v137_free_data import COHORT, WEATHER_ARCHIVE_START, historical_weather_for_game
from .v137_team_history import fetch_schedule_span

OUT_DIR = Path("data/v137")
REPORT = Path("data/v137_weather_backfill_report.json")


def _is_regular_game(game: dict[str, Any]) -> bool:
    return str(game.get("gameType") or "R").upper() == "R"


def _team_name(game: dict[str, Any], side: str) -> str:
    return str(((((game.get("teams") or {}).get(side) or {}).get("team") or {}).get("name")) or "")


def collect(start: str, end: str, lead_hours: int = 2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    games = fetch_schedule_span(start, end)
    rows = []
    status_counts = defaultdict(int)
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
        status_counts["available" if weather.get("available") else str(weather.get("reason") or "unavailable")] += 1
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
        "schema": "v13-7-free-weather-backfill-report-v1",
        "cohort": COHORT,
        "start": start,
        "end": end,
        "lead_hours": int(lead_hours),
        "archive_available_from": WEATHER_ARCHIVE_START.isoformat(),
        "rows": len(rows),
        "available_rows": sum(bool((r.get("weather") or {}).get("available")) for r in rows),
        "point_in_time_rows": sum(bool((r.get("weather") or {}).get("point_in_time")) for r in rows),
        "status_counts": dict(sorted(status_counts.items())),
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
    parser = argparse.ArgumentParser(description="Backfill free point-in-time archived ECMWF weather for MLB games")
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
