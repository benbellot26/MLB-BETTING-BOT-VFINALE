from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from . import engine_v12 as engine

SOURCE = Path("data/mlb_backtest_2026.jsonl")
OUTPUT = Path("data/v13_final_reconstructed_1801.jsonl")
REPORT = Path("data/v13_final_reconstructed_1801_report.json")
SCHEMA = "v13-final-reconstructed-from-2026-walkforward-v1"
WARM_MIN_GAMES = 5
TOTAL_DIAGNOSTIC_LINE = 8.5


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _clip(p: Any) -> float:
    return max(.001, min(.999, _num(p, .5)))


def _load() -> list[dict[str, Any]]:
    rows = []
    with SOURCE.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda r: (str(r.get("game_date") or ""), int(r.get("game_pk") or 0)))
    return rows


def _result(won: bool) -> str:
    return "WIN" if won else "LOSS"


def _ml_option(row: dict[str, Any]) -> dict[str, Any] | None:
    v10 = row.get("v10") or {}
    p = v10.get("p_home_raw")
    if p is None:
        return None
    hs, aws = int(row["home_score"]), int(row["away_score"])
    return {
        "market": "ML", "name": row.get("home"), "point": None,
        "is_canonical_line": True,
        "p_baseball_raw": _clip(p),
        "p_baseball_calibrated": None,
        "p_market": None, "p_posterior": None,
        "result": _result(hs > aws),
        "calibration_trainable": True,
        "source_probability": "v10.p_home_raw",
    }


def _rl_option(row: dict[str, Any]) -> dict[str, Any] | None:
    proxy = row.get("rl_proxy") or {}
    if proxy.get("p") is None or proxy.get("point") is None or proxy.get("result") not in {"W", "L"}:
        return None
    return {
        "market": "RUNLINE", "name": proxy.get("name"), "point": _num(proxy.get("point")),
        "is_canonical_line": True,
        "p_baseball_raw": _clip(proxy.get("p")),
        "p_baseball_calibrated": None,
        "p_market": None, "p_posterior": None,
        "result": "WIN" if proxy.get("result") == "W" else "LOSS",
        "calibration_trainable": True,
        "source_probability": "rl_proxy.p",
    }


def _total_diagnostic(row: dict[str, Any]) -> dict[str, Any] | None:
    v10 = row.get("v10") or {}
    hmu, amu = v10.get("home_mu"), v10.get("away_mu")
    if hmu is None or amu is None:
        return None
    win, push = engine.prob_total_parts(_num(hmu), _num(amu), "over", TOTAL_DIAGNOSTIC_LINE)
    # 8.5 cannot push, but keep the generic normalization explicit.
    p = win / max(1e-12, 1.0 - push)
    actual = int(row["home_score"]) + int(row["away_score"])
    return {
        "market": "TOTAL_DIAGNOSTIC", "name": "Over", "point": TOTAL_DIAGNOSTIC_LINE,
        "is_canonical_line": True,
        "p_baseball_raw": _clip(p),
        "p_baseball_calibrated": None,
        "p_market": None, "p_posterior": None,
        "result": _result(actual > TOTAL_DIAGNOSTIC_LINE),
        "calibration_trainable": False,
        "source_probability": "V13 NB distribution over historical v10 run means",
        "diagnostic_only_reason": "Synthetic fixed total line; no historical bookmaker total line exists.",
    }


def reconstruct(row: dict[str, Any]) -> dict[str, Any]:
    warm = int(row.get("pregame_games_home") or 0) >= WARM_MIN_GAMES and int(row.get("pregame_games_away") or 0) >= WARM_MIN_GAMES
    options = [x for x in (_ml_option(row), _rl_option(row), _total_diagnostic(row)) if x]
    v10 = row.get("v10") or {}
    return {
        "schema": SCHEMA,
        "game_pk": row.get("game_pk"), "game_date": row.get("game_date"),
        "home": row.get("home"), "away": row.get("away"),
        "home_score": row.get("home_score"), "away_score": row.get("away_score"),
        "result_status": "SETTLED",
        "phase": "FINAL",
        "historical_phase_origin": "FINAL_RECONSTRUCTED",
        "analyzed_at": None,
        "point_in_time": True,
        "point_in_time_basis": "walk-forward prediction emitted before current-game stats were added",
        "prediction_before_current_game_update": True,
        "current_game_stats_used": False,
        "market_probability_used_as_baseball_feature": False,
        "historical_odds_available": False,
        "identity_provenance": "Actual starter/lineup identity treated as FINAL-phase information; only prior stats contributed, per frozen source methodology.",
        "exact_pregame_timestamp_available": False,
        "replay_strength": "RECONSTRUCTED_FINAL_NOT_EXACT_HTTP_REPLAY",
        "warm_sample": warm,
        "pregame_games_home": row.get("pregame_games_home"),
        "pregame_games_away": row.get("pregame_games_away"),
        "starters": row.get("starters"),
        "league": row.get("league"),
        "projected_home_runs": v10.get("home_mu"),
        "projected_away_runs": v10.get("away_mu"),
        "structural_home_runs": v10.get("home_struct"),
        "structural_away_runs": v10.get("away_struct"),
        "options": options,
        "calibration_trainable": warm,
        "feature_trainable": False,
        "feature_trainable_reason": "Frozen V10 feature vector is not retained; use this cohort for probability calibration/distribution diagnostics, not V13 feature fitting.",
    }


def _metrics(rows: list[dict[str, Any]], market: str, warm_only: bool = True) -> dict[str, Any]:
    obs = []
    for row in rows:
        if warm_only and not row.get("warm_sample"):
            continue
        for opt in row.get("options") or []:
            if opt.get("market") == market and opt.get("result") in {"WIN", "LOSS"}:
                p = _clip(opt.get("p_baseball_raw")); y = 1.0 if opt["result"] == "WIN" else 0.0
                obs.append((p, y))
    if not obs:
        return {"n": 0}
    brier = sum((p-y)**2 for p,y in obs)/len(obs)
    ll = -sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in obs)/len(obs)
    bins = []
    for lo in (.50,.55,.60,.65,.70,.75,.80):
        hi = .55 if lo == .50 else lo+.05 if lo < .80 else 1.001
        xs = [(p,y) for p,y in obs if lo <= max(p,1-p) < hi]
        if xs:
            # Confidence-bin accuracy: prediction is whichever side has probability > .5.
            hit = sum((p >= .5) == bool(y) for p,y in xs)/len(xs)
            conf = sum(max(p,1-p) for p,_ in xs)/len(xs)
            bins.append({"range": f"{int(lo*100)}-{int(min(1,hi)*100)}", "n": len(xs), "avg_confidence": conf, "hit_rate": hit})
    return {"n": len(obs), "brier": brier, "logloss": ll, "confidence_bins": bins}


def build() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source = _load()
    rows = [reconstruct(r) for r in source]
    counts = Counter("warm" if r["warm_sample"] else "cold" for r in rows)
    report = {
        "schema": "v13-final-reconstructed-1801-report-v1",
        "source_games": len(source),
        "reconstructed_games": len(rows),
        "warm_games": counts["warm"],
        "cold_games": counts["cold"],
        "calibration_candidate_games": counts["warm"],
        "markets": {
            "ML": _metrics(rows, "ML"),
            "RUNLINE": _metrics(rows, "RUNLINE"),
            "TOTAL_DIAGNOSTIC_8_5": _metrics(rows, "TOTAL_DIAGNOSTIC"),
        },
        "provenance": {
            "source_methodology": "Frozen 2026 walk-forward: prediction before current-game stats update; expanding prior stats only.",
            "identity_scope": "FINAL_RECONSTRUCTED only",
            "exact_http_replay": False,
            "historical_market_odds": False,
            "market_used_in_baseball_probability": False,
            "totals_calibration_allowed": False,
            "ml_runline_calibration_allowed_on_warm_sample": True,
        },
        "evidence_hierarchy": [
            "EXACT_REPLAY: durable recorded HTTP replay (strongest)",
            "FINAL_RECONSTRUCTED: frozen chronological walk-forward with final-phase identity and prior stats only",
            "DIAGNOSTIC_ONLY: synthetic lines or incomplete provenance",
        ],
    }
    return rows, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()
    rows, report = build()
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))+"\n" for r in rows), encoding="utf-8")
    rp = Path(args.report); rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
