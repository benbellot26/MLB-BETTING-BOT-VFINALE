from __future__ import annotations

"""Controlled learning diagnostics for Pulsar V14.

This module NEVER mutates production model parameters. It turns settled PIT
predictions into evidence for a future challenger model. Promotion remains an
explicit, out-of-sample decision.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
import math

MIN_GAMES_FOR_DIAGNOSTIC = 50
MIN_GAMES_FOR_CHALLENGER = 200
MIN_MARKET_SAMPLES = 75
MIN_CALIBRATION_SAMPLES = 100


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _latest_settled(rows: list[dict[str, Any]], model_generation: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.get("settled") or row.get("model_generation") != model_generation:
            continue
        key = str(row.get("game_pk") or "")
        stamp = str(row.get("analyzed_at") or "")
        if not key:
            continue
        current = latest.get(key)
        if current is None or stamp > str(current.get("analyzed_at") or ""):
            latest[key] = row
    return list(latest.values())


def _metric(items: list[tuple[float, int]]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "brier": None, "log_loss": None, "bias_pp": None}
    eps = 1e-12
    mean_p = sum(p for p, _ in items) / len(items)
    observed = sum(y for _, y in items) / len(items)
    return {
        "n": len(items),
        "brier": sum((p - y) ** 2 for p, y in items) / len(items),
        "log_loss": -sum(y * math.log(max(eps, min(1-eps, p))) + (1-y) * math.log(max(eps, min(1-eps, 1-p))) for p, y in items) / len(items),
        "bias_pp": (mean_p - observed) * 100.0,
    }


def learning_report(rows: list[dict[str, Any]], model_generation: str) -> dict[str, Any]:
    settled = _latest_settled(rows, model_generation)
    markets: dict[str, list[tuple[float, int]]] = defaultdict(list)
    confidence_bins: dict[str, list[tuple[float, int]]] = defaultdict(list)

    for row in settled:
        probs = row.get("probabilities") or {}
        hs, aws = int(row["home_score"]), int(row["away_score"])
        total_line = _num(row.get("total_line"))
        observations = [
            ("ML_HOME", _num(probs.get("home_ml")), int(hs > aws)),
            ("RL_HOME_-1.5", _num(probs.get("home_minus_1_5")), int(hs - aws >= 2)),
            ("RL_AWAY_-1.5", _num(probs.get("away_minus_1_5")), int(aws - hs >= 2)),
        ]
        if total_line is not None:
            observations.append(("TOTAL_OVER", _num(probs.get("over")), int(hs + aws > total_line)))
        for market, p, y in observations:
            if p is None:
                continue
            markets[market].append((p, y))
            bucket = f"{int(p * 10) * 10:02d}-{min(100, int(p * 10) * 10 + 10):02d}%"
            confidence_bins[bucket].append((p, y))

    market_report = {name: _metric(items) for name, items in sorted(markets.items())}
    persistent_biases = []
    for name, metric in market_report.items():
        if metric["n"] >= MIN_MARKET_SAMPLES and metric["bias_pp"] is not None and abs(metric["bias_pp"]) >= 4.0:
            persistent_biases.append({"market": name, "n": metric["n"], "bias_pp": metric["bias_pp"]})

    calibration = {bucket: _metric(items) for bucket, items in sorted(confidence_bins.items()) if len(items) >= 10}
    n_games = len(settled)
    if n_games < MIN_GAMES_FOR_DIAGNOSTIC:
        stage = "COLLECTING"
        recommendation = "Collect more strictly-pregame settled games; do not tune production."
    elif n_games < MIN_GAMES_FOR_CHALLENGER:
        stage = "DIAGNOSTIC_ONLY"
        recommendation = "Inspect persistent biases only; production parameters remain frozen."
    else:
        stage = "CHALLENGER_ELIGIBLE"
        recommendation = "Enough history exists to train a separate challenger with chronological out-of-sample validation. No automatic promotion."

    return {
        "schema": "pulsar-v14-controlled-learning-v1",
        "model_generation": model_generation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "EVALUATION_ONLY",
        "production_mutation_allowed": False,
        "games": n_games,
        "stage": stage,
        "thresholds": {
            "diagnostic_games": MIN_GAMES_FOR_DIAGNOSTIC,
            "challenger_games": MIN_GAMES_FOR_CHALLENGER,
            "market_samples": MIN_MARKET_SAMPLES,
            "calibration_samples": MIN_CALIBRATION_SAMPLES,
        },
        "markets": market_report,
        "calibration": calibration,
        "persistent_biases": persistent_biases,
        "recommendation": recommendation,
        "promotion_policy": "A challenger must beat the production model on chronological holdout Brier/log-loss and calibration. Promotion is always explicit; never automatic.",
    }
