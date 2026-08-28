from __future__ import annotations

"""Prospective paired validation for the frozen historical team-run shadow."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION
from .acquisition import parse_time
from .historical_team_shadow import load as load_candidate, validate_artifact as validate_candidate

PREDICTIONS = Path("data/v14_predictions.jsonl")
OUTPUT = Path("data/v14_team_run_live_validation.json")
MIN_GAMES = 200


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _ci(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "ci95_lower": None, "ci95_upper": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"n": len(values), "mean": mean, "ci95_lower": None, "ci95_upper": None}
    var = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    se = math.sqrt(var / len(values))
    return {"n": len(values), "mean": mean, "ci95_lower": mean - 1.96 * se, "ci95_upper": mean + 1.96 * se}


def _loss(p: float, y: int) -> tuple[float, float]:
    q = max(1e-12, min(1 - 1e-12, p))
    return (p - y) ** 2, -(y * math.log(q) + (1 - y) * math.log(1 - q))


def _shadow(row: dict[str, Any]) -> dict[str, Any]:
    return (((row.get("training_features") or {}).get("research_challengers") or {}).get("historical_team_run_shadow") or {})


def _latest_postfreeze(rows: list[dict[str, Any]], freeze: datetime, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    source_run_id = candidate.get("source_run_id")
    candidate_id = candidate.get("candidate_id")
    candidate_fingerprint = candidate.get("candidate_fingerprint")
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("model_generation") != MODEL_GENERATION or row.get("settled") is not True:
            continue
        try:
            analyzed = parse_time(row.get("analyzed_at"))
            game = parse_time(row.get("game_date"))
        except Exception:
            continue
        if analyzed <= freeze or analyzed >= game:
            continue
        shadow = _shadow(row)
        if shadow.get("status") != "READY_SHADOW":
            continue
        if shadow.get("evidence_run_id") != source_run_id:
            continue
        if shadow.get("candidate_id") != candidate_id or shadow.get("candidate_fingerprint") != candidate_fingerprint:
            continue
        gid = str(row.get("game_pk") or "")
        if not gid:
            continue
        previous = latest.get(gid)
        if previous is None or parse_time(previous.get("analyzed_at")) < analyzed:
            latest[gid] = row
    return sorted(latest.values(), key=lambda row: parse_time(row.get("game_date")))


def build(rows: list[dict[str, Any]], artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate = load_candidate() if artifact is None else validate_candidate(artifact)
    base = {
        "schema": "pulsar-v14-historical-team-run-live-validation-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_generation": MODEL_GENERATION,
        "auto_activation": False,
        "champion_impact": False,
        "evidence_contract": "persisted READY_SHADOW before first pitch; exact candidate_id, candidate_fingerprint and source_run_id",
    }
    if not candidate:
        return {**base, "status": "COLLECTING", "reason": "validated frozen historical team-run artifact unavailable", "n": 0}
    try:
        freeze = parse_time(candidate.get("frozen_at"))
    except Exception:
        return {**base, "status": "COLLECTING", "reason": "candidate freeze timestamp invalid", "n": 0}

    scoped = _latest_postfreeze(rows, freeze, candidate)
    run_mse: list[float] = []
    total_mae: list[float] = []
    market = {name: {"brier": [], "logloss": [], "pushes": 0} for name in ("ML", "RL_HOME_-1.5", "RL_AWAY_-1.5", "TOTAL_OVER")}
    for row in scoped:
        hs = int(row["home_score"])
        aws = int(row["away_score"])
        shadow = _shadow(row)
        cr = shadow.get("candidate_run_projection") or {}
        ch, ca = _num(row.get("home_mu")), _num(row.get("away_mu"))
        srh, sra = _num(cr.get("home_mu")), _num(cr.get("away_mu"))
        if None not in (ch, ca, srh, sra):
            champion = ((hs - ch) ** 2 + (aws - ca) ** 2) / 2
            challenger = ((hs - srh) ** 2 + (aws - sra) ** 2) / 2
            run_mse.append(champion - challenger)
            total_mae.append(abs((hs + aws) - (ch + ca)) - abs((hs + aws) - (srh + sra)))

        cp = row.get("probabilities") or {}
        sp = shadow.get("candidate_probabilities") or {}
        line = _num(row.get("total_line"))
        definitions = [
            ("ML", "home_ml", int(hs > aws)),
            ("RL_HOME_-1.5", "home_minus_1_5", int(hs - aws >= 2)),
            ("RL_AWAY_-1.5", "away_minus_1_5", int(aws - hs >= 2)),
        ]
        if line is not None:
            if abs((hs + aws) - line) < 1e-9:
                market["TOTAL_OVER"]["pushes"] += 1
            else:
                definitions.append(("TOTAL_OVER", "over", int(hs + aws > line)))
        for name, key, y in definitions:
            champion_p, shadow_p = _num(cp.get(key)), _num(sp.get(key))
            if champion_p is None or shadow_p is None:
                continue
            champion_brier, champion_logloss = _loss(champion_p, y)
            shadow_brier, shadow_logloss = _loss(shadow_p, y)
            market[name]["brier"].append(champion_brier - shadow_brier)
            market[name]["logloss"].append(champion_logloss - shadow_logloss)

    run_ci = _ci(run_mse)
    total_ci = _ci(total_mae)
    markets = {
        name: {
            "n": len(data["brier"]),
            "brier_gain": _ci(data["brier"]),
            "logloss_gain": _ci(data["logloss"]),
            "pushes_excluded": data["pushes"],
        }
        for name, data in market.items()
    }
    enough = len(scoped) >= MIN_GAMES
    run_gain = run_ci.get("ci95_lower") is not None and float(run_ci["ci95_lower"]) > 0
    total_nonreg = total_ci.get("ci95_lower") is not None and float(total_ci["ci95_lower"]) >= -0.05
    ml = markets["ML"]
    ml_gain = bool(
        ml["brier_gain"].get("ci95_lower") is not None
        and float(ml["brier_gain"]["ci95_lower"]) > 0
        and ml["logloss_gain"].get("ci95_lower") is not None
        and float(ml["logloss_gain"]["ci95_lower"]) >= 0
    )
    market_nonreg = all(
        (item["brier_gain"].get("ci95_lower") is None or float(item["brier_gain"]["ci95_lower"]) >= -0.001)
        and (item["logloss_gain"].get("ci95_lower") is None or float(item["logloss_gain"]["ci95_lower"]) >= -0.003)
        for item in markets.values()
    )
    passes = bool(enough and run_gain and total_nonreg and ml_gain and market_nonreg)
    return {
        **base,
        "status": "PROMOTION_REVIEW" if passes else "COLLECTING" if not enough else "REJECTED_NATIVE_LIVE",
        "n": len(scoped),
        "required": MIN_GAMES,
        "candidate_id": candidate.get("candidate_id"),
        "candidate_fingerprint": candidate.get("candidate_fingerprint"),
        "candidate_source_run_id": candidate.get("source_run_id"),
        "candidate_frozen_at": candidate.get("frozen_at"),
        "evidence_artifact_sha256": ((candidate.get("source_validation_artifact") or {}).get("sha256")),
        "run_mse_gain": run_ci,
        "total_mae_gain": total_ci,
        "markets": markets,
        "gates": {
            "enough_games": enough,
            "paired_team_mse_ci95_positive": run_gain,
            "total_mae_nonregression": total_nonreg,
            "ml_brier_and_logloss_ci95_positive": ml_gain,
            "all_market_nonregression": market_nonreg,
            "passes": passes,
        },
        "promotion_policy": "PROMOTION_REVIEW is a human/versioned review state only; never auto-activate or change MODEL_GENERATION",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate historical team-run shadow on prospective native V14 predictions")
    parser.add_argument("--predictions", default=str(PREDICTIONS))
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    out = build(_read(args.predictions))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": out.get("status"), "n": out.get("n"), "gates": out.get("gates")}, sort_keys=True))


if __name__ == "__main__":
    main()
