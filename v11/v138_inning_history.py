from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any

from . import core
from . import v138_advanced_research as advanced
from . import v138_validation as validation

SCHEMA = "v13-8-free-inning-history-v1"
OUT = Path("data/v138_inning_history.json.gz")
REPORT = Path("data/v138_inning_evidence.json")


def _parse_day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _chunks(start: date, end: date, days: int = 31):
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=days - 1))
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch_schedule(start: str, end: str) -> list[dict[str, Any]]:
    """Free MLB schedule with final linescore hydration, chunked by month."""
    games: dict[str, dict[str, Any]] = {}
    for a, b in _chunks(_parse_day(start), _parse_day(end)):
        payload = core.mlb(
            "v1/schedule",
            {
                "sportId": 1,
                "startDate": a.isoformat(),
                "endDate": b.isoformat(),
                "gameTypes": "R",
                "hydrate": "linescore",
            },
        ) or {}
        for block in payload.get("dates") or []:
            for game in block.get("games") or []:
                gid = str(game.get("gamePk") or "")
                if gid:
                    games[gid] = game
    return sorted(games.values(), key=lambda g: str(g.get("gameDate") or ""))


def _final(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    return (
        str(status.get("abstractGameState") or "").lower() == "final"
        or str(status.get("codedGameState") or "").upper() == "F"
    )


def _score(game: dict[str, Any], side: str) -> int | None:
    value = (((game.get("teams") or {}).get(side) or {}).get("score"))
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _linescore(game: dict[str, Any]) -> dict[str, Any]:
    return game.get("linescore") or {}


def _inning_count(game: dict[str, Any]) -> int | None:
    ls = _linescore(game)
    innings = ls.get("innings") or []
    if innings:
        return len(innings)
    for key in ("currentInning", "currentInningOrdinal"):
        value = ls.get(key)
        if key == "currentInning" and value is not None:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _inning_runs_from_linescore(linescore: dict[str, Any]) -> tuple[list[int], list[int]] | None:
    innings = linescore.get("innings") or []
    if len(innings) < 9:
        return None
    home, away = [], []
    for inning in innings:
        try:
            home.append(int(((inning.get("home") or {}).get("runs")) or 0))
            away.append(int(((inning.get("away") or {}).get("runs")) or 0))
        except Exception:
            return None
    return home, away


def _feed_innings(game_pk: Any) -> tuple[list[int], list[int]] | None:
    try:
        feed = core.mlb(f"v1.1/game/{game_pk}/feed/live") or {}
        ls = (((feed.get("liveData") or {}).get("linescore")) or {})
        return _inning_runs_from_linescore(ls)
    except Exception:
        return None


def extract_extra(game: dict[str, Any]) -> dict[str, Any] | None:
    if not _final(game):
        return None
    hs, aws = _score(game, "home"), _score(game, "away")
    innings = _inning_count(game)
    if hs is None or aws is None or innings is None or innings <= 9:
        return None
    return {
        "game_pk": str(game.get("gamePk") or ""),
        "game_date": game.get("gameDate"),
        "season": int(str(game.get("officialDate") or game.get("gameDate") or "")[:4]),
        "extra_innings": True,
        "innings": innings,
        "home_win": int(hs > aws),
    }


def collect(
    games: list[dict[str, Any]],
    per_season_inning_target: int = 60,
    fetch_feed: bool = True,
) -> dict[str, Any]:
    """Build outcome-only extra-inning evidence and balanced inning profiles.

    Extra-inning identification uses final MLB linescore only. Inning arrays are
    sampled evenly by season; if schedule hydration omits them, the free MLB live
    feed is used for only the bounded profile sample, never for model features.
    """
    extras = []
    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        if not _final(game) or str(game.get("gameType") or "R").upper() != "R":
            continue
        extra = extract_extra(game)
        if extra:
            extras.append(extra)
        try:
            season = int(str(game.get("officialDate") or game.get("gameDate") or "")[:4])
        except Exception:
            continue
        if len(by_season[season]) >= per_season_inning_target:
            continue
        runs = _inning_runs_from_linescore(_linescore(game))
        source = "schedule_linescore"
        if runs is None and fetch_feed:
            runs = _feed_innings(game.get("gamePk"))
            source = "game_feed"
        if runs is None:
            continue
        home, away = runs
        by_season[season].append({
            "game_pk": str(game.get("gamePk") or ""),
            "game_date": game.get("gameDate"),
            "season": season,
            "home_innings": home,
            "away_innings": away,
            "source": source,
        })
    inning_rows = [row for season in sorted(by_season) for row in by_season[season]]
    extra_prior = validation.learn_extra_innings_home_prior(extras)
    inning_profile = advanced.fit_inning_profile(inning_rows, min_games=300)
    return {
        "schema": SCHEMA,
        "extras": extras,
        "inning_rows": inning_rows,
        "extra_inning_prior": extra_prior,
        "inning_profile": inning_profile,
        "season_profile_counts": {str(k): len(v) for k, v in sorted(by_season.items())},
        "label_only_policy": "final inning outcomes are label/prior evidence only; never inserted into target pregame features",
        "paid_sources_required": False,
    }


def write(payload: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump({"schema": SCHEMA, "extras": payload.get("extras") or [], "inning_rows": payload.get("inning_rows") or []}, fh,
                  ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    report = {
        "schema": "v13-8-free-inning-evidence-v1",
        "start": start,
        "end": end,
        "extra_inning_examples": len(payload.get("extras") or []),
        "inning_profile_games": len(payload.get("inning_rows") or []),
        "extra_inning_prior": payload.get("extra_inning_prior") or {},
        "inning_profile": payload.get("inning_profile") or {},
        "season_profile_counts": payload.get("season_profile_counts") or {},
        "paid_sources_required": False,
        "point_in_time_requirement": "not applicable to outcome-only historical prior labels; no target-game feature is reconstructed from its result",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(description="Build free historical inning/extra-inning evidence from MLB Stats API")
    parser.add_argument("--start", default="2021-04-01")
    parser.add_argument("--end", default=yesterday.isoformat())
    parser.add_argument("--per-season", type=int, default=60)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if REPORT.exists() and not args.force:
        try:
            existing = json.loads(REPORT.read_text(encoding="utf-8"))
            if (existing.get("extra_inning_prior") or {}).get("active") and (existing.get("inning_profile") or {}).get("active"):
                print(json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True))
                return
        except Exception:
            pass
    games = fetch_schedule(args.start, args.end)
    payload = collect(games, per_season_inning_target=max(50, int(args.per_season)), fetch_feed=True)
    report = write(payload, args.start, args.end)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
