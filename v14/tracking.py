from __future__ import annotations

"""Minimal native prediction tracking and settlement for Pulsar V14."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION
from .acquisition import mlb_schedule

PREDICTIONS = Path("data/v14_predictions.jsonl")
PERFORMANCE = Path("data/v14_performance.json")


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_jsonl(path: Path | str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def snapshot_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("model_generation") != MODEL_GENERATION:
        raise ValueError("tracking only accepts current V14 generation")
    target_date = str(payload.get("target_date") or "")
    rows: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        prediction = result.get("v14_prediction") or {}
        if prediction.get("model_generation") != MODEL_GENERATION:
            raise ValueError(f"game {result.get('game_pk')} is not current V14")
        probabilities = prediction.get("probabilities") or {}
        projection = prediction.get("run_projection") or {}
        total_line = _num(projection.get("total_line"))
        if total_line is None:
            total_line = _num((result.get("canonical_lines") or {}).get("TOTAL"))
        rows.append({
            "schema": "pulsar-v14-prediction-record-v1",
            "model_generation": MODEL_GENERATION,
            "game_pk": str(result.get("game_pk") or ""),
            "target_date": target_date or str(result.get("game_date") or "")[:10],
            "game_date": result.get("game_date"),
            "analyzed_at": result.get("analyzed_at") or payload.get("analyzed_at"),
            "home": result.get("home"),
            "away": result.get("away"),
            "home_mu": _num(projection.get("home_mu")),
            "away_mu": _num(projection.get("away_mu")),
            "total_line": total_line,
            "probabilities": {
                key: _num(probabilities.get(key))
                for key in (
                    "home_ml", "away_ml", "home_minus_1_5", "away_plus_1_5",
                    "away_minus_1_5", "home_plus_1_5", "over", "under",
                )
            },
            "settled": False,
            "home_score": None,
            "away_score": None,
            "settled_at": None,
        })
    return rows


def append_snapshot(payload: dict[str, Any], path: Path | str = PREDICTIONS) -> int:
    existing = _read_jsonl(path)
    index = {
        (str(row.get("game_pk") or ""), str(row.get("analyzed_at") or "")): row
        for row in existing
    }
    before = len(index)
    for row in snapshot_rows(payload):
        key = (str(row.get("game_pk") or ""), str(row.get("analyzed_at") or ""))
        index[key] = row
    ordered = sorted(index.values(), key=lambda row: (str(row.get("target_date") or ""), str(row.get("game_pk") or ""), str(row.get("analyzed_at") or "")))
    _write_jsonl(path, ordered)
    return len(index) - before


def _final_scores(game: dict[str, Any]) -> tuple[int, int] | None:
    status = ((game.get("status") or {}).get("abstractGameState") or "").lower()
    detailed = ((game.get("status") or {}).get("detailedState") or "").lower()
    if status != "final" and "final" not in detailed and "completed" not in detailed:
        return None
    teams = game.get("teams") or {}
    home = _num((teams.get("home") or {}).get("score"))
    away = _num((teams.get("away") or {}).get("score"))
    if home is None or away is None:
        return None
    return int(home), int(away)


def settle_predictions(
    path: Path | str = PREDICTIONS,
    *,
    schedule_loader: Callable[[str], list[dict[str, Any]]] | None = None,
) -> int:
    rows = _read_jsonl(path)
    loader = schedule_loader or (lambda day: mlb_schedule(day, hydrate="linescore"))
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("settled"):
            by_day[str(row.get("target_date") or "")].append(row)

    settled = 0
    now = datetime.now(timezone.utc).isoformat()
    for day, pending in by_day.items():
        if not day:
            continue
        games = {str(game.get("gamePk") or ""): game for game in loader(day)}
        for row in pending:
            game = games.get(str(row.get("game_pk") or ""))
            scores = _final_scores(game or {}) if game else None
            if scores is None:
                continue
            row["home_score"], row["away_score"] = scores
            row["settled"] = True
            row["settled_at"] = now
            settled += 1
    _write_jsonl(path, rows)
    return settled


def _binary_metrics(items: list[tuple[float, int]]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy_50": None, "mean_probability": None, "observed_rate": None}
    eps = 1e-12
    brier = sum((p - y) ** 2 for p, y in items) / len(items)
    log_loss = -sum(y * math.log(max(eps, min(1 - eps, p))) + (1 - y) * math.log(max(eps, min(1 - eps, 1 - p))) for p, y in items) / len(items)
    return {
        "n": len(items),
        "brier": brier,
        "log_loss": log_loss,
        "accuracy_50": sum((p >= 0.5) == bool(y) for p, y in items) / len(items),
        "mean_probability": sum(p for p, _ in items) / len(items),
        "observed_rate": sum(y for _, y in items) / len(items),
    }


def _calibration(items: list[tuple[float, int]], bins: int = 10) -> list[dict[str, Any]]:
    grouped: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in items:
        idx = min(bins - 1, max(0, int(p * bins)))
        grouped[idx].append((p, y))
    out = []
    for idx, values in enumerate(grouped):
        if not values:
            continue
        out.append({
            "lower": idx / bins,
            "upper": (idx + 1) / bins,
            "n": len(values),
            "mean_probability": sum(p for p, _ in values) / len(values),
            "observed_rate": sum(y for _, y in values) / len(values),
        })
    return out


def _canonical_settled(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    settled_records = [row for row in rows if row.get("settled") and row.get("model_generation") == MODEL_GENERATION]
    latest_by_game: dict[str, dict[str, Any]] = {}
    for row in settled_records:
        key = str(row.get("game_pk") or "")
        current = latest_by_game.get(key)
        if current is None or str(row.get("analyzed_at") or "") > str(current.get("analyzed_at") or ""):
            latest_by_game[key] = row
    canonical = sorted(latest_by_game.values(), key=lambda row: (str(row.get("target_date") or ""), str(row.get("game_pk") or "")))
    return canonical, len(settled_records)


def performance_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled, settled_record_count = _canonical_settled(rows)
    markets: dict[str, list[tuple[float, int]]] = defaultdict(list)
    run_errors: list[float] = []
    total_errors: list[float] = []

    for row in settled:
        hs = int(row["home_score"])
        aws = int(row["away_score"])
        probs = row.get("probabilities") or {}
        home_ml = _num(probs.get("home_ml"))
        home_rl = _num(probs.get("home_minus_1_5"))
        away_rl = _num(probs.get("away_minus_1_5"))
        over = _num(probs.get("over"))
        line = _num(row.get("total_line"))
        if home_ml is not None:
            markets["ML"].append((home_ml, int(hs > aws)))
        if home_rl is not None:
            markets["RL_HOME_-1.5"].append((home_rl, int(hs - aws >= 2)))
        if away_rl is not None:
            markets["RL_AWAY_-1.5"].append((away_rl, int(aws - hs >= 2)))
        if over is not None and line is not None:
            markets["TOTAL_OVER"].append((over, int(hs + aws > line)))
        hmu, amu = _num(row.get("home_mu")), _num(row.get("away_mu"))
        if hmu is not None and amu is not None:
            run_errors.extend((abs(hmu - hs), abs(amu - aws)))
            total_errors.append(abs((hmu + amu) - (hs + aws)))

    all_items = [item for values in markets.values() for item in values]
    return {
        "schema": "pulsar-v14-performance-v1",
        "model_generation": MODEL_GENERATION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prediction_records_settled": settled_record_count,
        "games_settled": len(settled),
        "canonical_snapshot_policy": "latest pregame snapshot per game",
        "overall": _binary_metrics(all_items),
        "calibration": _calibration(all_items),
        "markets": {name: {**_binary_metrics(values), "calibration": _calibration(values)} for name, values in sorted(markets.items())},
        "runs": {
            "team_run_mae": sum(run_errors) / len(run_errors) if run_errors else None,
            "total_run_mae": sum(total_errors) / len(total_errors) if total_errors else None,
        },
        "roi": {"status": "UNAVAILABLE", "reason": "No official bet/stake ledger in V14 analytics-only production."},
        "clv": {"status": "UNAVAILABLE", "reason": "Closing prices are not yet persisted as a canonical V14 input."},
    }


def write_performance(path: Path | str = PREDICTIONS, report_path: Path | str = PERFORMANCE) -> dict[str, Any]:
    report = performance_report(_read_jsonl(path))
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Pulsar V14 native prediction tracking")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--payload", default="runtime/v14/discord_payload.json")
    snap.add_argument("--predictions", default=str(PREDICTIONS))
    settle = sub.add_parser("settle")
    settle.add_argument("--predictions", default=str(PREDICTIONS))
    settle.add_argument("--report", default=str(PERFORMANCE))
    args = parser.parse_args()

    if args.command == "snapshot":
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        added = append_snapshot(payload, args.predictions)
        print(f"PULSAR_V14_TRACKING snapshot_added={added}")
    else:
        settled = settle_predictions(args.predictions)
        report = write_performance(args.predictions, args.report)
        print(f"PULSAR_V14_TRACKING settled={settled} games={report['games_settled']}")


if __name__ == "__main__":
    main()
