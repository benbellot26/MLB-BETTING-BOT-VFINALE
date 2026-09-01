from __future__ import annotations

"""Unified research diagnostics for frozen Pulsar V14 predictions.

The scorer is intentionally post-hoc and read-only. It never authorizes a wager
and never rewrites champion probabilities.
"""

import argparse
from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Iterable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .paired_inference import bootstrap_mean_ci, paired_score_differences

DEFAULT_PREDICTIONS = Path("data/v14_predictions.jsonl")
DEFAULT_OUTPUT = Path("data/v14_research_diagnostics.json")

MARKETS = {
    "ML_HOME": "home_ml",
    "RL_HOME_-1.5": "home_minus_1_5",
    "RL_AWAY_-1.5": "away_minus_1_5",
    "TOTAL_OVER": "over",
}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


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


def _policy(row: dict[str, Any]) -> str | None:
    direct = row.get("probability_policy_id")
    nested = (row.get("calibration") or {}).get("probability_policy_id")
    value = direct or nested
    return str(value) if value else None


def current_settled(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one deterministic latest pregame current-policy snapshot per game.

    Research dashboards must not inflate evidence by counting repeated snapshots of
    the same MLB game as independent observations. Betting certification remains
    narrower and uses its own first-SCHEDULED_FINAL selector.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.get("settled"):
            continue
        if row.get("model_generation") != MODEL_GENERATION or _policy(row) != PROBABILITY_POLICY_ID:
            continue
        analyzed, game = _parse(row.get("analyzed_at")), _parse(row.get("game_date"))
        if analyzed is None or game is None or analyzed >= game:
            continue
        if _num(row.get("home_score")) is None or _num(row.get("away_score")) is None:
            continue
        game_pk = str(row.get("game_pk") or "")
        if not game_pk:
            continue
        previous = latest.get(game_pk)
        previous_at = _parse(previous.get("analyzed_at")) if previous else None
        if previous is None or previous_at is None or analyzed > previous_at:
            latest[game_pk] = row
    return sorted(
        latest.values(),
        key=lambda row: (_parse(row.get("game_date")) or datetime.min, str(row.get("game_pk") or "")),
    )


def _outcome(row: dict[str, Any], market: str) -> int | None:
    hs, aws = int(float(row["home_score"])), int(float(row["away_score"]))
    if market == "ML_HOME":
        return int(hs > aws)
    if market == "RL_HOME_-1.5":
        return int(hs - aws >= 2)
    if market == "RL_AWAY_-1.5":
        return int(aws - hs >= 2)
    if market == "TOTAL_OVER":
        line = _num(row.get("total_line"))
        if line is None or abs((hs + aws) - line) < 1e-9:
            return None
        return int(hs + aws > line)
    return None


def binary_metrics(items: list[tuple[float, int]]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "brier": None, "log_loss": None, "ece": None}
    eps = 1e-12
    brier = sum((p - y) ** 2 for p, y in items) / len(items)
    log_loss = -sum(
        y * math.log(max(eps, min(1 - eps, p)))
        + (1 - y) * math.log(max(eps, min(1 - eps, 1 - p)))
        for p, y in items
    ) / len(items)
    bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, y in items:
        bins[min(9, max(0, int(p * 10)))].append((p, y))
    ece = 0.0
    for bucket in bins.values():
        mp = sum(p for p, _ in bucket) / len(bucket)
        oy = sum(y for _, y in bucket) / len(bucket)
        ece += len(bucket) / len(items) * abs(mp - oy)
    return {"n": len(items), "brier": brier, "log_loss": log_loss, "ece": ece}


def _sharp_probability(row: dict[str, Any], selection: str) -> float | None:
    return _num((((row.get("sharp_market") or {}).get("selections") or {}).get(selection) or {}).get("fair_probability"))


def _variant_probability(row: dict[str, Any], variant: str, selection: str) -> float | None:
    variants = row.get("research_variants") or {}
    payload = variants.get(variant) or {}
    probs = payload.get("probabilities") if isinstance(payload, dict) else None
    if not isinstance(probs, dict) and isinstance(payload, dict):
        probs = payload
    return _num((probs or {}).get(selection))


def _paired_summary(pairs: list[tuple[float, float, int]], label: str) -> dict[str, Any]:
    if not pairs:
        return {
            "n": 0,
            "brier_gain": None,
            "brier_gain_ci95_lower": None,
            "brier_gain_ci95_upper": None,
            "logloss_gain": None,
            "logloss_gain_ci95_lower": None,
            "logloss_gain_ci95_upper": None,
        }
    diffs = paired_score_differences(pairs)
    brier_ci = bootstrap_mean_ci(diffs["brier_gain"], label=f"{label}|brier")
    log_ci = bootstrap_mean_ci(diffs["logloss_gain"], label=f"{label}|logloss")
    return {
        "n": len(pairs),
        "brier_gain": brier_ci["mean"],
        "brier_gain_ci95_lower": brier_ci["ci95_lower"],
        "brier_gain_ci95_upper": brier_ci["ci95_upper"],
        "logloss_gain": log_ci["mean"],
        "logloss_gain_ci95_lower": log_ci["ci95_lower"],
        "logloss_gain_ci95_upper": log_ci["ci95_upper"],
        "method": brier_ci["method"],
    }


def baseline_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for market, selection in MARKETS.items():
        champion: list[tuple[float, int]] = []
        vs_coin: list[tuple[float, float, int]] = []
        vs_sharp: list[tuple[float, float, int]] = []
        for row in rows:
            y = _outcome(row, market)
            p = _num((row.get("probabilities") or {}).get(selection))
            if y is None or p is None:
                continue
            champion.append((p, y))
            vs_coin.append((p, 0.5, y))
            sharp = _sharp_probability(row, selection)
            if sharp is not None:
                vs_sharp.append((p, sharp, y))
        out[market] = {
            "champion": binary_metrics(champion),
            "paired_vs_coin_50": _paired_summary(vs_coin, f"{market}|coin"),
            "paired_vs_sharp": _paired_summary(vs_sharp, f"{market}|sharp"),
        }
    return out


def variant_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted(
        {
            str(name)
            for row in rows
            for name in (row.get("research_variants") or {})
        }
    )
    output: dict[str, Any] = {}
    for name in names:
        market_rows: dict[str, Any] = {}
        for market, selection in MARKETS.items():
            pairs: list[tuple[float, float, int]] = []
            variant_items: list[tuple[float, int]] = []
            for row in rows:
                y = _outcome(row, market)
                champion = _num((row.get("probabilities") or {}).get(selection))
                variant = _variant_probability(row, name, selection)
                if y is None or champion is None or variant is None:
                    continue
                variant_items.append((variant, y))
                pairs.append((variant, champion, y))
            market_rows[market] = {
                "variant": binary_metrics(variant_items),
                "paired_vs_champion": _paired_summary(pairs, f"{name}|{market}|champion"),
            }
        output[name] = market_rows
    return output


def _regime_labels(row: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    game = _parse(row.get("game_date"))
    if game:
        labels["month"] = f"{game.year:04d}-{game.month:02d}"
        labels["season_phase"] = (
            "APR_MAY" if game.month <= 5
            else "JUN_JUL" if game.month <= 7
            else "AUG_SEP" if game.month <= 9
            else "POSTSEASON"
        )
    home_ml = _num((row.get("probabilities") or {}).get("home_ml"))
    if home_ml is not None:
        labels["home_model_state"] = (
            "HOME_STRONG_FAVORITE" if home_ml >= 0.60
            else "HOME_SLIGHT_FAVORITE" if home_ml >= 0.50
            else "HOME_STRONG_UNDERDOG" if home_ml <= 0.40
            else "HOME_SLIGHT_UNDERDOG"
        )
    hmu, amu = _num(row.get("home_mu")), _num(row.get("away_mu"))
    if hmu is not None and amu is not None:
        projected_total = hmu + amu
        labels["run_environment"] = (
            "LOW_<7.5" if projected_total < 7.5
            else "MID_7.5_9.0" if projected_total <= 9.0
            else "HIGH_>9.0"
        )
    phase = str(row.get("phase") or "").upper()
    if phase:
        labels["snapshot_phase"] = phase
    return labels


def regime_report(rows: list[dict[str, Any]], *, min_slice_n: int = 10) -> dict[str, Any]:
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for dimension, label in _regime_labels(row).items():
            buckets[dimension][label].append(row)
    output: dict[str, Any] = {}
    for dimension, groups in buckets.items():
        output[dimension] = {}
        for label, sample in sorted(groups.items()):
            per_market = {}
            for market, selection in MARKETS.items():
                items = []
                for row in sample:
                    y = _outcome(row, market)
                    p = _num((row.get("probabilities") or {}).get(selection))
                    if y is not None and p is not None:
                        items.append((p, y))
                metrics = binary_metrics(items)
                metrics["diagnostic_only_small_slice"] = metrics["n"] < min_slice_n
                per_market[market] = metrics
            output[dimension][label] = {"games": len(sample), "markets": per_market}
    return output


def evidence_health(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len({str(row.get("game_pk") or "") for row in rows})
    maturity = (
        "VERY_EARLY" if n < 50
        else "EARLY" if n < 200
        else "DEVELOPING" if n < 600
        else "MATURE_SAMPLE_SIZE_ONLY"
    )
    return {
        "independent_games": n,
        "maturity": maturity,
        "sample_size_is_not_certification": True,
        "required_joint_evidence": [
            "calibration",
            "proper_score_vs_sharp",
            "prospective_CLV",
            "temporal_stability",
            "confidence_intervals",
            "execution_quality",
        ],
    }


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = current_settled(rows)
    return {
        "schema": "pulsar-v14-research-diagnostics-v1",
        "role": "RESEARCH_ONLY",
        "champion_impact": False,
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "evidence_health": evidence_health(settled),
        "baselines": baseline_report(settled),
        "shadow_variants_and_ablations": variant_report(settled),
        "regimes": regime_report(settled),
        "notes": [
            "Sharp/coin comparisons are paired on identical settled games.",
            "Named variants are scored only when prospectively persisted in research_variants.",
            "Regime slices are descriptive and must not be mined post-hoc into production rules.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only V14 research diagnostics")
    parser.add_argument("--predictions", default=str(DEFAULT_PREDICTIONS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = build_report(_read_jsonl(args.predictions))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "games": report["evidence_health"]["independent_games"]}, sort_keys=True))


if __name__ == "__main__":
    main()
