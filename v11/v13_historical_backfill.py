from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Activates the complete hardened V12 stack plus V13 probability contract.
from . import v13_entry  # noqa: F401
from . import core, engine_v12 as engine

SCHEMA = "v13-point-in-time-backfill-v1"
OUTPUT_FILE = Path(os.getenv("V13_BACKFILL_FILE", "data/v13_historical_backfill.jsonl"))
REPORT_FILE = Path(os.getenv("V13_BACKFILL_REPORT", "data/v13_historical_backfill_report.json"))


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _norm(x: Any) -> str:
    return "".join(c.lower() for c in str(x or "") if c.isalnum())


def _live_final_scores(day: str) -> dict[str, tuple[int, int]]:
    """Fetch labels only. These values are never exposed to feature generation."""
    params = urllib.parse.urlencode({"sportId": 1, "date": day, "hydrate": "linescore"})
    url = f"https://statsapi.mlb.com/api/v1/schedule?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "MLB-V13-label-backfill"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out: dict[str, tuple[int, int]] = {}
    for block in data.get("dates") or []:
        for game in block.get("games") or []:
            status = game.get("status") or {}
            if str(status.get("abstractGameState") or "").lower() != "final" and str(status.get("codedGameState") or "").upper() != "F":
                continue
            teams = game.get("teams") or {}
            hs = (teams.get("home") or {}).get("score")
            aws = (teams.get("away") or {}).get("score")
            if hs is not None and aws is not None:
                out[str(game.get("gamePk"))] = (int(hs), int(aws))
    return out


def _settle(opt: dict[str, Any], home: str, hs: int, aws: int) -> str | None:
    market = str(opt.get("market") or "").upper()
    name = str(opt.get("name") or "")
    point = opt.get("point")
    if market == "ML":
        home_side = _norm(name) == _norm(home)
        won = hs > aws if home_side else aws > hs
        return "WIN" if won else "LOSS"
    if market == "RUNLINE" and point is not None:
        home_side = _norm(name) == _norm(home)
        margin = (hs-aws if home_side else aws-hs) + _num(point)
        if abs(margin) <= 1e-9:
            return "PUSH"
        return "WIN" if margin > 0 else "LOSS"
    if market == "TOTAL" and point is not None:
        delta = hs+aws-_num(point)
        if abs(delta) <= 1e-9:
            return "PUSH"
        over = name.lower() == "over"
        return "WIN" if (delta > 0) == over else "LOSS"
    return None


def _option_row(opt: dict[str, Any], home: str, hs: int, aws: int) -> dict[str, Any]:
    keys = (
        "market", "name", "point", "is_canonical_line", "line_source",
        "p_structural", "p_learned", "p_baseball_raw", "p_baseball_calibrated",
        "p_effective", "p_win", "p_push", "p_push_model", "p_market", "p_posterior",
        "model_market_gap", "probability_interval_low", "probability_interval_high",
        "calibration_source_v13", "calibration_n_v13", "probability_product",
        "refs", "sharp_books", "sharp_weight", "sharp_dispersion", "sharp_robustness",
        "sharp_effective_n", "quality", "model_uncertainty",
    )
    out = {k: opt.get(k) for k in keys}
    out["result"] = _settle(opt, home, hs, aws)
    return out


def replay_one(path: Path, score_cache: dict[str, dict[str, tuple[int, int]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    old_date, old_season = core.TARGET_DATE, core.SEASON
    rows: list[dict[str, Any]] = []
    diag: dict[str, Any] = {"source": path.name, "status": "ERROR", "rows": 0}
    try:
        payload = core.load_http_replay(path)
        day = str(payload.get("target_date") or "")
        analyzed_at = str(payload.get("analyzed_at") or "")
        if not day or not analyzed_at:
            raise ValueError("missing target_date/analyzed_at")
        core.TARGET_DATE = day
        core.SEASON = int(day[:4])
        core._CACHE.clear()
        games = core.mlb_schedule(day)
        events = core.odds_api()
        matches = core.match_odds_events(games, events)
        results = []
        for game in games:
            try:
                if core.parse_dt(game.get("gameDate")) <= core.parse_dt(analyzed_at):
                    continue
            except Exception:
                continue
            event = matches.get(str(game.get("gamePk")))
            if not event:
                continue
            try:
                results.append(engine.analyze(game, event, as_of=analyzed_at))
            except Exception as exc:
                # A replay can legitimately be incomplete for a later code path.
                diag.setdefault("analysis_errors", []).append({"game_pk": game.get("gamePk"), "error": f"{type(exc).__name__}:{exc}"})
        core.clear_http_replay()
        if day not in score_cache:
            score_cache[day] = _live_final_scores(day)
        scores = score_cache[day]
        for result in results:
            gid = str(result.get("game_pk"))
            if gid not in scores:
                continue
            hs, aws = scores[gid]
            ctx = result.get("ctx") or {}
            options = [_option_row(o, str(ctx.get("home") or ""), hs, aws) for o in result.get("options") or []]
            rows.append({
                "schema": SCHEMA,
                "source_replay_schema": payload.get("schema"),
                "run_id": payload.get("run_id"),
                "source_replay": path.name,
                "analyzed_at": analyzed_at,
                "target_date": day,
                "game_pk": result.get("game_pk"),
                "game_date": (result.get("game") or {}).get("gameDate"),
                "home": ctx.get("home"), "away": ctx.get("away"),
                "phase": result.get("phase"),
                "projected_home_runs": result.get("hmu"),
                "projected_away_runs": result.get("amu"),
                "structural_home_runs": result.get("structural_hmu"),
                "structural_away_runs": result.get("structural_amu"),
                "home_score": hs, "away_score": aws,
                "result_status": "SETTLED",
                "point_in_time": True,
                "label_source": "postgame MLB Stats API; labels only",
                "features_from_postgame": False,
                "market_probability_used_as_baseball_feature": False,
                "probability_contract_version": result.get("probability_contract_version"),
                "options": options,
            })
        diag.update({"status": "PASS", "day": day, "analyzed_at": analyzed_at, "games_in_replay": len(games), "analyzed": len(results), "rows": len(rows)})
        return rows, diag
    except Exception as exc:
        diag["error"] = f"{type(exc).__name__}:{exc}"
        return [], diag
    finally:
        core.clear_http_replay()
        core.TARGET_DATE, core.SEASON = old_date, old_season
        core._CACHE.clear()


def _canonical(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep latest pregame observation per game and phase; retain phases independently."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("game_pk")), str(row.get("phase") or "EARLY").upper())
        current = best.get(key)
        if current is None or str(row.get("analyzed_at") or "") > str(current.get("analyzed_at") or ""):
            best[key] = row
    return sorted(best.values(), key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or ""), str(r.get("phase") or "")))


def build(paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    score_cache: dict[str, dict[str, tuple[int, int]]] = {}
    all_rows: list[dict[str, Any]] = []
    diagnostics = []
    for path in sorted(paths):
        rows, diag = replay_one(path, score_cache)
        all_rows.extend(rows)
        diagnostics.append(diag)
    canonical = _canonical(all_rows)
    phase_counts = Counter(str(r.get("phase") or "UNKNOWN") for r in canonical)
    market_counts = Counter()
    for row in canonical:
        for opt in row.get("options") or []:
            if opt.get("result") in {"WIN", "LOSS", "PUSH"}:
                market_counts[str(opt.get("market") or "UNKNOWN")] += 1
    report = {
        "schema": "v13-historical-backfill-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_replays": len(paths),
        "replay_pass": sum(d.get("status") == "PASS" for d in diagnostics),
        "replay_fail": sum(d.get("status") != "PASS" for d in diagnostics),
        "raw_rows": len(all_rows),
        "canonical_rows": len(canonical),
        "canonical_games": len({str(r.get("game_pk")) for r in canonical}),
        "phase_counts": dict(phase_counts),
        "settled_options_by_market": dict(market_counts),
        "diagnostics": diagnostics,
        "evidence_boundary": "All features come exclusively from recorded pregame HTTP replays. Final MLB scores are fetched after replay and used only as labels.",
    }
    return canonical, report


def main() -> None:
    p = argparse.ArgumentParser(description="V13 point-in-time backfill from durable source replays")
    p.add_argument("paths", nargs="*", help="Replay .json.gz files")
    p.add_argument("--dir", dest="directory")
    p.add_argument("--output", default=str(OUTPUT_FILE))
    p.add_argument("--report", default=str(REPORT_FILE))
    args = p.parse_args()
    paths = [Path(x) for x in args.paths]
    if args.directory:
        paths.extend(Path(args.directory).glob("*_sources.json.gz"))
    paths = sorted({p.resolve() for p in paths if p.exists()})
    rows, report = build(paths)
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))+"\n" for r in rows), encoding="utf-8")
    rp = Path(args.report); rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
