from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import random
from typing import Any

from . import MODEL_GENERATION
from .benchmark import CHAMPION_GENERATION
from .model import ProbabilitySurface
from .validation import brier, logloss, outcomes

SHADOW_FILE = Path("data/v14_shadow_predictions.jsonl")
LABEL_FILE = Path("data/v13_label_store.jsonl")
REPORT_FILE = Path("data/v14_paired_evidence.json")
SCHEMA = "v14-paired-evidence-v1"
LABEL_SCHEMA = "v13-label-store-v1"
MIN_PAIRED_GAMES = 300
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_MIN_POSITIVE_PROBABILITY = 0.90


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            continue
    return out


def _surface(payload: Any) -> ProbabilitySurface | None:
    if not isinstance(payload, dict):
        return None
    try:
        values = {key: float(payload[key]) for key in ProbabilitySurface.__dataclass_fields__}
        return ProbabilitySurface(**values).validated(tolerance=2e-6)
    except Exception:
        return None


def _valid_shadow(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("model_generation") != MODEL_GENERATION:
        return False, "wrong_v14_generation"
    if str(row.get("role") or "") != "SHADOW_ONLY" or row.get("affects_production") is not False:
        return False, "not_shadow_only"
    if str(row.get("phase") or "").upper() != "FINAL":
        return False, "not_final_phase"
    analyzed, game_time = _dt(row.get("analyzed_at")), _dt(row.get("game_date"))
    if analyzed is None or game_time is None or analyzed >= game_time:
        return False, "not_pregame"
    if _surface(row.get("probabilities")) is None:
        return False, "invalid_v14_surface"
    champion = row.get("champion_reference") or {}
    if champion.get("role") != "FROZEN_CHAMPION_BENCHMARK_ONLY":
        return False, "champion_reference_missing"
    if champion.get("model_generation") != CHAMPION_GENERATION:
        return False, "wrong_champion_generation"
    if champion.get("used_as_v14_model_input") is not False:
        return False, "champion_reference_input_violation"
    if _surface(champion.get("probabilities")) is None:
        return False, "invalid_champion_surface"
    if row.get("market_probability_used_as_feature") is not False:
        return False, "market_feature_violation"
    return True, "PASS"


def _valid_label(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("schema") != LABEL_SCHEMA:
        return False, "wrong_label_schema"
    if not row.get("game_pk") or row.get("home_score") is None or row.get("away_score") is None:
        return False, "incomplete_label"
    game_time, settled = _dt(row.get("game_date")), _dt(row.get("settled_at"))
    if game_time is None or settled is None or settled < game_time:
        return False, "label_not_postgame_attested"
    try:
        hs, aps = int(row["home_score"]), int(row["away_score"])
    except Exception:
        return False, "invalid_score"
    if hs < 0 or aps < 0 or hs == aps:
        return False, "invalid_mlb_final_score"
    return True, "PASS"


def _latest_final_shadows(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], Counter]:
    best: dict[str, dict[str, Any]] = {}
    rejects: Counter = Counter()
    for row in rows:
        valid, reason = _valid_shadow(row)
        if not valid:
            rejects[reason] += 1
            continue
        gid = str(row.get("game_pk") or "")
        if not gid:
            rejects["missing_game_pk"] += 1
            continue
        rank = str(row.get("analyzed_at") or "")
        old = best.get(gid)
        if old is None or rank > str(old.get("analyzed_at") or ""):
            best[gid] = row
    return best, rejects


def _latest_labels(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], Counter]:
    best: dict[str, dict[str, Any]] = {}
    rejects: Counter = Counter()
    for row in rows:
        valid, reason = _valid_label(row)
        if not valid:
            rejects[reason] += 1
            continue
        gid = str(row.get("game_pk"))
        rank = str(row.get("settled_at") or "")
        old = best.get(gid)
        if old is None or rank > str(old.get("settled_at") or ""):
            best[gid] = row
    return best, rejects


def _target_losses(surface: ProbabilitySurface, *, home_score: int, away_score: int,
                   total_line: float) -> dict[str, dict[str, float]]:
    ys = outcomes(home_score, away_score, total_line)
    targets = {
        "home_ml": (surface.home_ml, ys["home_ml"]),
        "home_minus_1_5": (surface.home_minus_1_5, ys["home_minus_1_5"]),
        "home_plus_1_5": (surface.home_plus_1_5, ys["home_plus_1_5"]),
        "over": (surface.over, ys["over"]),
    }
    return {
        key: {"brier": brier(p, y), "logloss": logloss(p, y)}
        for key, (p, y) in targets.items()
    }


def _game_losses(row: dict[str, Any], label: dict[str, Any]) -> dict[str, Any]:
    v14 = _surface(row.get("probabilities"))
    champion = _surface((row.get("champion_reference") or {}).get("probabilities"))
    if v14 is None or champion is None:
        raise ValueError("invalid paired probability surface")
    total_line = float(row["total_line"])
    hs, aps = int(label["home_score"]), int(label["away_score"])
    v = _target_losses(v14, home_score=hs, away_score=aps, total_line=total_line)
    c = _target_losses(champion, home_score=hs, away_score=aps, total_line=total_line)

    def market_view(losses: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        runline_brier = 0.5 * (losses["home_minus_1_5"]["brier"] + losses["home_plus_1_5"]["brier"])
        runline_logloss = 0.5 * (losses["home_minus_1_5"]["logloss"] + losses["home_plus_1_5"]["logloss"])
        markets = {
            "ML": dict(losses["home_ml"]),
            "RUNLINE": {"brier": runline_brier, "logloss": runline_logloss},
            "TOTAL": dict(losses["over"]),
        }
        markets["OVERALL"] = {
            "brier": sum(markets[m]["brier"] for m in ("ML", "RUNLINE", "TOTAL")) / 3.0,
            "logloss": sum(markets[m]["logloss"] for m in ("ML", "RUNLINE", "TOTAL")) / 3.0,
        }
        return markets

    return {
        "game_pk": str(row.get("game_pk")),
        "game_date": row.get("game_date"),
        "analyzed_at": row.get("analyzed_at"),
        "total_line": total_line,
        "v14": market_view(v),
        "champion": market_view(c),
    }


def _aggregate(games: list[dict[str, Any]], market: str) -> dict[str, Any]:
    if not games:
        return {"n_games": 0, "v14_brier": None, "champion_brier": None, "brier_gain_vs_champion": None,
                "v14_logloss": None, "champion_logloss": None, "logloss_gain_vs_champion": None}
    n = len(games)
    vb = sum(g["v14"][market]["brier"] for g in games) / n
    cb = sum(g["champion"][market]["brier"] for g in games) / n
    vl = sum(g["v14"][market]["logloss"] for g in games) / n
    cl = sum(g["champion"][market]["logloss"] for g in games) / n
    return {
        "n_games": n,
        "v14_brier": vb,
        "champion_brier": cb,
        "brier_gain_vs_champion": cb - vb,
        "v14_logloss": vl,
        "champion_logloss": cl,
        "logloss_gain_vs_champion": cl - vl,
    }


def _bootstrap(games: list[dict[str, Any]], market: str) -> dict[str, Any]:
    if len(games) < 10:
        return {"draws": 0, "brier_gain_positive_probability": None,
                "logloss_gain_positive_probability": None, "passes": False}
    brier_gains = [g["champion"][market]["brier"] - g["v14"][market]["brier"] for g in games]
    logloss_gains = [g["champion"][market]["logloss"] - g["v14"][market]["logloss"] for g in games]
    rng = random.Random(f"v14-paired-{market}-1")
    b_pos = l_pos = 0
    n = len(games)
    for _ in range(BOOTSTRAP_DRAWS):
        idx = [rng.randrange(n) for _ in range(n)]
        bg = sum(brier_gains[i] for i in idx) / n
        lg = sum(logloss_gains[i] for i in idx) / n
        b_pos += bg > 0
        l_pos += lg > 0
    bp = b_pos / BOOTSTRAP_DRAWS
    lp = l_pos / BOOTSTRAP_DRAWS
    return {
        "draws": BOOTSTRAP_DRAWS,
        "brier_gain_positive_probability": bp,
        "logloss_gain_positive_probability": lp,
        "minimum_positive_probability": BOOTSTRAP_MIN_POSITIVE_PROBABILITY,
        "passes": bp >= BOOTSTRAP_MIN_POSITIVE_PROBABILITY and lp >= BOOTSTRAP_MIN_POSITIVE_PROBABILITY,
    }


def build(shadow_rows: list[dict[str, Any]] | None = None,
          label_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    shadows = _read_jsonl(SHADOW_FILE) if shadow_rows is None else list(shadow_rows)
    labels = _read_jsonl(LABEL_FILE) if label_rows is None else list(label_rows)
    final_shadows, shadow_rejects = _latest_final_shadows(shadows)
    final_labels, label_rejects = _latest_labels(labels)

    games: list[dict[str, Any]] = []
    unmatched = 0
    for gid, shadow in final_shadows.items():
        label = final_labels.get(gid)
        if label is None:
            unmatched += 1
            continue
        games.append(_game_losses(shadow, label))
    games.sort(key=lambda g: (str(g.get("game_date") or ""), g["game_pk"]))

    markets: dict[str, Any] = {}
    for market in ("ML", "RUNLINE", "TOTAL", "OVERALL"):
        metrics = _aggregate(games, market)
        metrics["bootstrap"] = _bootstrap(games, market)
        markets[market] = metrics

    enough = len(games) >= MIN_PAIRED_GAMES
    all_markets_positive = all(
        markets[m].get("brier_gain_vs_champion") is not None
        and float(markets[m]["brier_gain_vs_champion"]) >= 0
        and markets[m].get("logloss_gain_vs_champion") is not None
        and float(markets[m]["logloss_gain_vs_champion"]) >= 0
        and (markets[m].get("bootstrap") or {}).get("passes") is True
        for m in ("ML", "RUNLINE", "TOTAL")
    )
    paired_gate_passes = bool(enough and all_markets_positive)
    blockers = [
        "INDEPENDENT_V14_RUN_MODEL_NOT_IMPLEMENTED",
        "V14_CALIBRATION_NOT_INDEPENDENTLY_VALIDATED",
    ]
    if not enough:
        blockers.append(f"PAIRED_GAMES_{len(games)}_OF_{MIN_PAIRED_GAMES}")
    if enough and not all_markets_positive:
        blockers.append("MARKET_LEVEL_PROPER_SCORE_OR_BOOTSTRAP_GATE_FAILED")

    return {
        "schema": SCHEMA,
        "v14_model_generation": MODEL_GENERATION,
        "champion_generation": CHAMPION_GENERATION,
        "role": "PAIRED_SHADOW_EVIDENCE_ONLY",
        "promotion_allowed": False,
        "paired_comparison_gate_passes": paired_gate_passes,
        "promotion_blockers": blockers,
        "minimum_paired_games": MIN_PAIRED_GAMES,
        "paired_games": len(games),
        "eligible_final_shadow_games": len(final_shadows),
        "eligible_final_labels": len(final_labels),
        "unmatched_final_shadows": unmatched,
        "shadow_rejections": dict(shadow_rejects),
        "label_rejections": dict(label_rejects),
        "markets": markets,
        "sample_policy": {
            "unit": "one unique MLB game",
            "phase": "FINAL pregame snapshot only",
            "snapshot": "latest valid FINAL pregame V14 snapshot per game",
            "ml": "home ML canonical binary target",
            "runline": "home -1.5 and home +1.5 proper losses averaged inside each game; n remains one game",
            "total": "Over at the exact half-run line persisted with the forecast",
            "overall": "equal-weight mean of ML, game-aggregated RUNLINE and TOTAL losses",
            "label_join": "separate v13-label-store-v1 row with settled_at >= game_date",
            "champion_reference_used_as_v14_input": False,
        },
        "game_ids": [g["game_pk"] for g in games],
    }


def save(report: dict[str, Any], path: Path = REPORT_FILE) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Score paired V14 shadow vs frozen V13.10 champion")
    parser.add_argument("--shadow", default=str(SHADOW_FILE))
    parser.add_argument("--labels", default=str(LABEL_FILE))
    parser.add_argument("--output", default=str(REPORT_FILE))
    args = parser.parse_args()
    report = build(_read_jsonl(Path(args.shadow)), _read_jsonl(Path(args.labels)))
    save(report, Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
