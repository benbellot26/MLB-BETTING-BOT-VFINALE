from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any

from . import core
from . import v137_park_factors as park_factors
from .v137_free_data import COHORT, reconstructed_feature_envelope

SCHEMA = "v13-7-free-team-history-v2"
FEATURE_DIR = Path("data/v137")
REPORT_FILE = Path("data/v137_free_team_history_report.json")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _parse_day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _chunks(start: date, end: date, days: int = 31):
    current = start
    while current <= end:
        stop = min(end, current + timedelta(days=days - 1))
        yield current, stop
        current = stop + timedelta(days=1)


def fetch_schedule_span(start: str, end: str) -> list[dict[str, Any]]:
    """Fetch only free MLB regular-season schedule/results data in bounded chunks."""
    s, e = _parse_day(start), _parse_day(end)
    games: dict[str, dict[str, Any]] = {}
    for a, b in _chunks(s, e):
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
        for block in payload.get("dates") or []:
            for game in block.get("games") or []:
                gid = str(game.get("gamePk") or "")
                if gid:
                    games[gid] = game
    return sorted(games.values(), key=lambda g: str(g.get("gameDate") or ""))


def _team_side(game: dict[str, Any], side: str) -> tuple[str, str, int | None]:
    item = ((game.get("teams") or {}).get(side) or {})
    team = item.get("team") or {}
    score = item.get("score")
    return str(team.get("id") or ""), str(team.get("name") or ""), int(score) if score is not None else None


def _is_final(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    return (
        str(status.get("abstractGameState") or "").lower() == "final"
        or str(status.get("codedGameState") or "").upper() == "F"
    )


def _official_day(game: dict[str, Any]) -> str:
    value = game.get("officialDate")
    if value:
        return str(value)[:10]
    return str(game.get("gameDate") or "")[:10]


def _prior_summary(history: list[dict[str, Any]], official_day: str, n: int | None = None) -> dict[str, Any]:
    """Use only games from earlier official calendar dates.

    Excluding same-day finals is deliberately conservative for historical
    doubleheaders because the archive does not timestamp when the final became
    public. Native-live collection handles Game 1 -> Game 2 separately.
    """
    prior = [g for g in history if str(g.get("official_day") or "") < official_day]
    if n is not None:
        prior = prior[-n:]
    if not prior:
        return {
            "games": 0,
            "runs_for_pg": None,
            "runs_against_pg": None,
            "run_diff_pg": None,
            "win_pct": None,
        }
    games = len(prior)
    rf = sum(_num(g.get("runs_for")) for g in prior)
    ra = sum(_num(g.get("runs_against")) for g in prior)
    wins = sum(_num(g.get("win")) for g in prior)
    return {
        "games": games,
        "runs_for_pg": rf / games,
        "runs_against_pg": ra / games,
        "run_diff_pg": (rf - ra) / games,
        "win_pct": wins / games,
    }


def _rest_days(history: list[dict[str, Any]], official_day: str) -> int | None:
    prior_days = [str(g.get("official_day")) for g in history if str(g.get("official_day") or "") < official_day]
    if not prior_days:
        return None
    delta = (_parse_day(official_day) - _parse_day(max(prior_days))).days - 1
    return max(0, min(10, delta))


def _team_features(history: list[dict[str, Any]], official_day: str) -> dict[str, Any]:
    return {
        "season_to_date": _prior_summary(history, official_day, None),
        "last_7_games": _prior_summary(history, official_day, 7),
        "last_14_games": _prior_summary(history, official_day, 14),
        "last_30_games": _prior_summary(history, official_day, 30),
        "rest_days": _rest_days(history, official_day),
    }


def build_from_games(
    games: list[dict[str, Any]],
    park_artifact: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Create compact leakage-separated free historical team features and labels."""
    history: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    features: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    skipped = defaultdict(int)
    park_artifact = park_factors.load() if park_artifact is None else park_artifact
    park_available = 0

    ordered = sorted(games, key=lambda g: (str(g.get("gameDate") or ""), str(g.get("gamePk") or "")))
    for game in ordered:
        if str(game.get("gameType") or "").upper() != "R":
            skipped["non_regular_season"] += 1
            continue
        if not _is_final(game):
            skipped["not_final"] += 1
            continue
        official_day = _official_day(game)
        try:
            season = int(official_day[:4])
            game_time = core.parse_dt(game.get("gameDate"))
        except Exception:
            skipped["bad_game_time"] += 1
            continue
        home_id, home, hs = _team_side(game, "home")
        away_id, away, aws = _team_side(game, "away")
        if hs is None or aws is None or not home_id or not away_id:
            skipped["missing_score_or_team"] += 1
            continue

        venue = str(((game.get("venue") or {}).get("name")) or "")
        park_prior = park_factors.venue_prior(park_artifact, season, venue) if venue else {
            "available": False,
            "target_season": season,
            "venue": venue,
            "point_in_time": True,
        }
        park_available += int(bool(park_prior.get("available")))
        home_hist = history[(season, home_id)]
        away_hist = history[(season, away_id)]
        as_of = game_time - timedelta(hours=2)
        feature_payload = {
            "home_team_form": _team_features(home_hist, official_day),
            "away_team_form": _team_features(away_hist, official_day),
            "park_prior": park_prior,
            "home_field": True,
            "official_date": official_day,
        }
        provenance = {
            "mlb_prior_results": {
                "provider": "MLB Stats API",
                "point_in_time_rule": "strictly earlier officialDate only",
                "max_eligible_official_date": (date.fromisoformat(official_day) - timedelta(days=1)).isoformat(),
                "same_day_games_excluded": True,
            }
        }
        if park_prior.get("available"):
            provenance["park_prior"] = {
                "provider": "Baseball Savant Statcast Park Factors",
                "point_in_time": True,
                "source_window_end_season": park_prior.get("source_window_end_season"),
                "rule": "three completed seasons ending before target season",
            }
        row = reconstructed_feature_envelope(
            game_pk=game.get("gamePk"),
            game_time=game_time,
            as_of=as_of,
            home=home,
            away=away,
            home_id=home_id,
            away_id=away_id,
            features=feature_payload,
            provenance=provenance,
        )
        row.update(
            {
                "schema": SCHEMA,
                "season": season,
                "official_date": official_day,
                "venue_id": ((game.get("venue") or {}).get("id")),
                "venue_name": venue,
            }
        )
        features.append(row)
        labels.append(
            {
                "schema": "v13-7-free-team-label-v1",
                "cohort": COHORT,
                "game_pk": game.get("gamePk"),
                "game_date": game_time.astimezone(timezone.utc).isoformat(),
                "official_date": official_day,
                "home": home,
                "away": away,
                "home_score": hs,
                "away_score": aws,
                "home_win": int(hs > aws),
                "total_runs": hs + aws,
                "run_margin_home": hs - aws,
                "label_source": "MLB Stats API final result; stored separately from feature row",
            }
        )

        home_hist.append(
            {
                "official_day": official_day,
                "runs_for": hs,
                "runs_against": aws,
                "win": int(hs > aws),
            }
        )
        away_hist.append(
            {
                "official_day": official_day,
                "runs_for": aws,
                "runs_against": hs,
                "win": int(aws > hs),
            }
        )

    report = {
        "schema": "v13-7-free-team-history-report-v2",
        "cohort": COHORT,
        "feature_rows": len(features),
        "label_rows": len(labels),
        "unique_games": len({str(r.get("game_pk")) for r in features}),
        "seasons": sorted({int(r.get("season")) for r in features}),
        "park_prior_rows": park_available,
        "park_prior_coverage": park_available / len(features) if features else 0.0,
        "skipped": dict(sorted(skipped.items())),
        "native_live": False,
        "promotion_eligible": False,
        "leakage_policy": "target labels separate; target and same-day scores never enter target feature row; park factors end before target season",
    }
    return features, labels, report


def _write_gzip_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def write_by_season(features: list[dict[str, Any]], labels: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    seasons = sorted({int(r["season"]) for r in features})
    for season in seasons:
        fs = [r for r in features if int(r.get("season")) == season]
        ls = [r for r in labels if str(r.get("official_date") or "").startswith(str(season))]
        fp = FEATURE_DIR / f"team_features_{season}.jsonl.gz"
        lp = FEATURE_DIR / f"team_labels_{season}.jsonl.gz"
        _write_gzip_jsonl(fp, fs)
        _write_gzip_jsonl(lp, ls)
        paths.extend([str(fp), str(lp)])
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build free MLB point-in-time team-history research features")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    games = fetch_schedule_span(args.start, args.end)
    features, labels, report = build_from_games(games)
    report["start"] = args.start
    report["end"] = args.end
    report["files"] = write_by_season(features, labels)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
