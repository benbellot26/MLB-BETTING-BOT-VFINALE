from __future__ import annotations

import argparse
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import core

OUT = Path("data/v137_mlb_state_latest.json.gz")
REPORT = Path("data/v137_mlb_state_report.json")
ARCHIVE_DIR = Path("data/v137/mlb_state")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date(value: date) -> str:
    return value.isoformat()


def _team_list(season: int) -> list[dict[str, Any]]:
    payload = core.mlb(
        "v1/teams",
        {"sportIds": 1, "season": int(season), "activeStatus": "Y"},
    ) or {}
    teams = []
    for team in payload.get("teams") or []:
        tid = team.get("id")
        if not tid:
            continue
        teams.append(
            {
                "id": int(tid),
                "name": team.get("name"),
                "abbreviation": team.get("abbreviation"),
            }
        )
    return sorted(teams, key=lambda t: int(t["id"]))


def _roster(team_id: int, snapshot_day: str) -> dict[str, Any]:
    payload = core.mlb(
        f"v1/teams/{int(team_id)}/roster",
        {"rosterType": "active", "date": snapshot_day, "hydrate": "person"},
    ) or {}
    players = []
    for item in payload.get("roster") or []:
        person = item.get("person") or {}
        pos = item.get("position") or {}
        status = item.get("status") or {}
        if not person.get("id"):
            continue
        players.append(
            {
                "person_id": int(person["id"]),
                "name": person.get("fullName"),
                "position_code": pos.get("code"),
                "position": pos.get("abbreviation") or pos.get("name"),
                "status_code": status.get("code"),
                "status": status.get("description"),
            }
        )
    return {
        "team_id": int(team_id),
        "roster_type": "active",
        "snapshot_day": snapshot_day,
        "players": players,
        "player_count": len(players),
    }


def _transactions(start_day: str, end_day: str) -> list[dict[str, Any]]:
    payload = core.mlb(
        "v1/transactions",
        {
            "sportId": 1,
            "startDate": start_day,
            "endDate": end_day,
            "limit": 1000,
        },
    ) or {}
    out = []
    for item in payload.get("transactions") or []:
        person = item.get("person") or {}
        to_team = item.get("toTeam") or {}
        from_team = item.get("fromTeam") or {}
        desc = str(item.get("description") or "")
        type_desc = str(item.get("typeDesc") or "")
        text = f"{type_desc} {desc}".lower()
        il_signal = any(token in text for token in ("injured list", "day injured", "60-day", "15-day", "10-day"))
        out.append(
            {
                "id": item.get("id"),
                "person_id": person.get("id"),
                "person": person.get("fullName"),
                "to_team_id": to_team.get("id"),
                "to_team": to_team.get("name"),
                "from_team_id": from_team.get("id"),
                "from_team": from_team.get("name"),
                "date": item.get("date"),
                "effective_date": item.get("effectiveDate"),
                "resolution_date": item.get("resolutionDate"),
                "type_code": item.get("typeCode"),
                "type_desc": type_desc or None,
                "description": desc or None,
                "injured_list_signal": bool(il_signal),
            }
        )
    return out


def collect(snapshot_day: str | None = None, transaction_lookback_days: int = 14) -> tuple[dict[str, Any], dict[str, Any]]:
    day = date.fromisoformat(snapshot_day) if snapshot_day else datetime.now(timezone.utc).date()
    observed_at = _iso_now()
    season = day.year
    teams = _team_list(season)
    rosters: dict[str, Any] = {}
    roster_failures = []
    for team in teams:
        tid = int(team["id"])
        try:
            rosters[str(tid)] = {**team, **_roster(tid, day.isoformat())}
        except Exception as exc:
            rosters[str(tid)] = {**team, "players": [], "player_count": 0, "error": type(exc).__name__}
            roster_failures.append({"team_id": tid, "error": type(exc).__name__})
    lookback = max(1, min(60, int(transaction_lookback_days)))
    start = day - timedelta(days=lookback)
    try:
        transactions = _transactions(_date(start), _date(day))
        transaction_error = None
    except Exception as exc:
        transactions = []
        transaction_error = f"{type(exc).__name__}:{exc}"
    artifact = {
        "schema": "v13-7-mlb-native-state-v1",
        "observed_at": observed_at,
        "snapshot_day": day.isoformat(),
        "season": season,
        "provider": "MLB Stats API",
        "point_in_time": True,
        "native_live": True,
        "promotion_eligible": False,
        "teams": teams,
        "active_rosters": rosters,
        "transactions": transactions,
        "transaction_window": {"start": start.isoformat(), "end": day.isoformat()},
        "injured_list_transaction_signals": [t for t in transactions if t.get("injured_list_signal")],
        "limitations": [
            "transaction-derived injured-list signals are not a complete injury report",
            "daily roster snapshot does not reconstruct unknown historical intraday roster states",
            "use observed_at for all future point-in-time joins",
        ],
    }
    report = {
        "schema": "v13-7-mlb-native-state-report-v1",
        "observed_at": observed_at,
        "snapshot_day": day.isoformat(),
        "teams": len(teams),
        "rosters_ok": sum(1 for r in rosters.values() if not r.get("error")),
        "roster_failures": roster_failures,
        "transactions": len(transactions),
        "injured_list_transaction_signals": len(artifact["injured_list_transaction_signals"]),
        "transaction_error": transaction_error,
        "point_in_time": True,
        "native_live": True,
        "promotion_eligible": False,
    }
    return artifact, report


def _write_gzip(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect free MLB native roster/transaction PIT snapshot")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; omit for current UTC date")
    parser.add_argument("--transaction-lookback-days", type=int, default=14)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()
    artifact, report = collect(args.date, args.transaction_lookback_days)
    _write_gzip(OUT, artifact)
    if args.archive:
        archive = ARCHIVE_DIR / f"mlb_state_{artifact['snapshot_day']}.json.gz"
        _write_gzip(archive, artifact)
        report["archive"] = str(archive)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
