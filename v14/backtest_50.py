from __future__ import annotations

"""Audit the exact 50-game V13 reference block against the isolated V14 shadow.

The script is intentionally conservative. It never manufactures historical
starter/lineup/bullpen context. If the current PIT feature store does not contain
an eligible snapshot at or before the historical prediction timestamp, the V14
context layer is a no-op and that fact is reported explicitly.
"""

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .context_overlay import context_overlay_from_feature_row
from .distribution import probability_surface
from .feature_row import feature_row_is_usable
from .model import RunProjection
from .v13_context_adapter import adapt_feature_row

VALIDATION = Path("data/v13_historical_validation.json")
BACKFILL = Path("data/v13_historical_backfill.jsonl")
FEATURE_STORE = Path("data/v13_feature_store.jsonl")
OUT_JSON = Path("data/v14_backtest_50_report.json")
OUT_MD = Path("data/v14_backtest_50_report.md")
PHASE_RANK = {"EARLY": 0, "LATE": 1, "FINAL": 2}


def _dt(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _brier(probs: list[float], ys: list[int]) -> float | None:
    if not probs:
        return None
    return sum((p-y)**2 for p, y in zip(probs, ys)) / len(probs)


def _logloss(probs: list[float], ys: list[int]) -> float | None:
    if not probs:
        return None
    eps = 1e-12
    return -sum(y*math.log(max(eps, min(1-eps, p))) + (1-y)*math.log(max(eps, min(1-eps, 1-p))) for p, y in zip(probs, ys)) / len(probs)


def _accuracy(probs: list[float], ys: list[int]) -> float | None:
    if not probs:
        return None
    return sum((p >= .5) == bool(y) for p, y in zip(probs, ys)) / len(probs)


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    usable = [r for r in rows if r.get("result") in {"WIN", "LOSS"} and _num(r.get(key)) is not None]
    probs = [float(r[key]) for r in usable]
    ys = [1 if r["result"] == "WIN" else 0 for r in usable]
    return {"n": len(usable), "brier": _brier(probs, ys), "logloss": _logloss(probs, ys), "accuracy_at_50": _accuracy(probs, ys), "mean_probability": (sum(probs)/len(probs) if probs else None)}


def _latest_phase_by_game(observations: list[dict[str, Any]]) -> dict[str, str]:
    phases: dict[str, str] = {}
    for obs in observations:
        gid = str(obs.get("game_pk") or "")
        phase = str(obs.get("phase") or "EARLY").upper()
        if not gid:
            continue
        if gid not in phases or PHASE_RANK.get(phase, -1) > PHASE_RANK.get(phases[gid], -1):
            phases[gid] = phase
    return phases


def _select_feature(features_by_game: dict[str, list[dict[str, Any]]], *, game_pk: str, cutoff: Any) -> dict[str, Any] | None:
    best = None
    best_dt = None
    for row in features_by_game.get(game_pk, []):
        if not feature_row_is_usable(row, game_pk=game_pk, as_of=cutoff):
            continue
        observed = _dt(row.get("as_of") or row.get("analyzed_at"))
        if observed is not None and (best_dt is None or observed > best_dt):
            best, best_dt = row, observed
    return best


def _surface_probability(surface: Any, obs: dict[str, Any], home: str, away: str) -> float | None:
    market = str(obs.get("market") or "").upper()
    pick = str(obs.get("pick") or "")
    point = _num(obs.get("point"))
    if market == "ML":
        if pick == home:
            return surface.home_ml
        if pick == away:
            return surface.away_ml
    elif market == "RUNLINE" and point is not None and abs(abs(point)-1.5) < 1e-9:
        if pick == home and point < 0:
            return surface.home_minus_1_5
        if pick == home and point > 0:
            return surface.home_plus_1_5
        if pick == away and point < 0:
            return surface.away_minus_1_5
        if pick == away and point > 0:
            return surface.away_plus_1_5
    elif market == "TOTAL":
        if pick.lower() == "over":
            return surface.over
        if pick.lower() == "under":
            return surface.under
    return None


def build_report() -> dict[str, Any]:
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    all_obs = [x for x in validation.get("observations", []) if isinstance(x, dict)]
    block = [x for x in all_obs if int(x.get("validation_block") or 0) == 0]
    game_ids = sorted({str(x.get("game_pk")) for x in block if x.get("game_pk") is not None})
    if len(game_ids) != int(validation.get("block_games") or 50):
        raise RuntimeError(f"expected exactly {validation.get('block_games')} block-0 games, found {len(game_ids)}")

    latest_phase = _latest_phase_by_game(block)
    canonical_obs = [x for x in block if str(x.get("phase") or "").upper() == latest_phase.get(str(x.get("game_pk")))]

    backfill_rows = _read_jsonl(BACKFILL)
    backfill_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in backfill_rows:
        backfill_by_key[(str(row.get("game_pk") or ""), str(row.get("phase") or "EARLY").upper())].append(row)

    feature_rows = _read_jsonl(FEATURE_STORE)
    features_by_game: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in feature_rows:
        features_by_game[str(row.get("game_pk") or "")].append(row)

    evaluated = []
    coverage_games = set()
    missing_backfill_games = set()
    context_changed_games = set()
    baseline_generation = set()

    for obs in canonical_obs:
        gid = str(obs.get("game_pk"))
        phase = str(obs.get("phase") or "EARLY").upper()
        candidates = backfill_by_key.get((gid, phase), [])
        if not candidates:
            missing_backfill_games.add(gid)
            continue
        # Prefer the snapshot closest to game time within this exact phase.
        backfill = sorted(candidates, key=lambda r: str(r.get("analyzed_at") or ""))[-1]
        cutoff = backfill.get("analyzed_at")
        feature = _select_feature(features_by_game, game_pk=gid, cutoff=cutoff)
        if feature is not None:
            coverage_games.add(gid)
        adapted = adapt_feature_row(feature)

        home = str(backfill.get("home") or "")
        away = str(backfill.get("away") or "")
        home_mu = _num(backfill.get("projected_home_runs"))
        away_mu = _num(backfill.get("projected_away_runs"))
        if home_mu is None or away_mu is None:
            continue
        overlay = context_overlay_from_feature_row(adapted, home_mu, away_mu)
        if abs(float(overlay.get("home_delta") or 0.0)) > 1e-12 or abs(float(overlay.get("away_delta") or 0.0)) > 1e-12:
            context_changed_games.add(gid)

        market = str(obs.get("market") or "").upper()
        total_line = _num(obs.get("point")) if market == "TOTAL" else 8.5
        if total_line is None or abs(total_line*2-round(total_line*2)) > 1e-9 or round(total_line*2) % 2 == 0:
            # V14 display surface contract supports half-run totals only. ML/RL
            # are independent of the chosen display total, while whole-run TOTAL
            # targets are omitted from this strict comparison.
            if market == "TOTAL":
                continue
            total_line = 8.5

        projection = RunProjection(
            game_pk=gid,
            game_date=str(backfill.get("game_date") or ""),
            analyzed_at=str(backfill.get("analyzed_at") or ""),
            home=home,
            away=away,
            home_mu=float(overlay["home_mu"]),
            away_mu=float(overlay["away_mu"]),
            total_line=float(total_line),
            phase=phase,
            dispersion=float(_num(backfill.get("validation_baseline_dispersion")) or 7.5),
            environment_sigma=float(_num(backfill.get("validation_baseline_environment_sigma")) or 0.08),
            extra_innings_home_probability=0.5,
            source_generation=str(backfill.get("validation_baseline_model_generation") or ""),
        ).validated()
        surface, _tail = probability_surface(projection)
        p14 = _surface_probability(surface, obs, home, away)
        p13 = _num(obs.get("p_raw"))
        if p13 is None:
            p13 = _num(obs.get("p_baseball_calibrated"))
        if p14 is None or p13 is None:
            continue

        baseline_generation.add(str(backfill.get("validation_baseline_model_generation") or ""))
        evaluated.append({
            "game_pk": gid,
            "game_date": backfill.get("game_date"),
            "phase": phase,
            "home": home,
            "away": away,
            "market": market,
            "pick": obs.get("pick"),
            "point": obs.get("point"),
            "result": obs.get("settled_result"),
            "v13_probability": p13,
            "v14_probability": p14,
            "probability_delta": p14-p13,
            "context_snapshot_available": feature is not None,
            "context_applied": gid in context_changed_games,
            "home_delta": overlay.get("home_delta"),
            "away_delta": overlay.get("away_delta"),
        })

    by_market = {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        rows = [r for r in evaluated if r["market"] == market]
        m13, m14 = _metrics(rows, "v13_probability"), _metrics(rows, "v14_probability")
        by_market[market] = {
            "v13": m13,
            "v14": m14,
            "brier_improvement_v14_minus_v13": (None if m13["brier"] is None or m14["brier"] is None else m13["brier"]-m14["brier"]),
            "logloss_improvement_v14_minus_v13": (None if m13["logloss"] is None or m14["logloss"] is None else m13["logloss"]-m14["logloss"]),
        }

    all13, all14 = _metrics(evaluated, "v13_probability"), _metrics(evaluated, "v14_probability")
    changed_rows = [r for r in evaluated if abs(r["probability_delta"]) > 1e-9]
    max_abs_delta = max((abs(r["probability_delta"]) for r in evaluated), default=0.0)

    report = {
        "schema": "v14-50-game-reference-backtest-v1",
        "reference": {
            "validation_file": str(VALIDATION),
            "validation_block": 0,
            "expected_games": int(validation.get("block_games") or 50),
            "unique_games": len(game_ids),
            "canonical_phase_policy": "latest available phase per unique game, matching V13 pooled promotion independence",
            "historical_baseline_generation": sorted(baseline_generation),
            "current_v13_10_generation": "v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3",
            "generation_match_current_v13_10": baseline_generation == {"v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3"},
        },
        "coverage": {
            "historical_backfill_games_missing": len(missing_backfill_games),
            "current_v13_feature_store_context_games": len(coverage_games),
            "context_overlay_changed_games": len(context_changed_games),
            "strict_context_coverage_pct": 100.0*len(coverage_games)/len(game_ids) if game_ids else 0.0,
            "interpretation": "If contextual coverage is zero, this validates V14 distribution/parity only; the new Quantum-inspired contextual modules are not historically identifiable on this block and must not be credited with any gain/loss.",
        },
        "overall": {
            "evaluated_market_observations": len(evaluated),
            "v13": all13,
            "v14": all14,
            "brier_improvement_v14_minus_v13": (None if all13["brier"] is None or all14["brier"] is None else all13["brier"]-all14["brier"]),
            "logloss_improvement_v14_minus_v13": (None if all13["logloss"] is None or all14["logloss"] is None else all13["logloss"]-all14["logloss"]),
            "rows_with_probability_change": len(changed_rows),
            "max_absolute_probability_delta": max_abs_delta,
        },
        "by_market": by_market,
        "rows": evaluated,
    }
    return report


def _fmt(x: Any, digits: int = 6) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def write_report(report: dict[str, Any]) -> None:
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    ref, cov, overall = report["reference"], report["coverage"], report["overall"]
    lines = [
        "# Pulsar V14 — 50-game V13 reference backtest",
        "",
        f"- Reference games: **{ref['unique_games']}** (validation block 0)",
        f"- Historical V13 generation: `{', '.join(ref['historical_baseline_generation'])}`",
        f"- Same as current V13.10 champion: **{ref['generation_match_current_v13_10']}**",
        f"- Exact current contextual snapshots available: **{cov['current_v13_feature_store_context_games']}/{ref['unique_games']}**",
        f"- Games where V14 contextual overlay actually changed run means: **{cov['context_overlay_changed_games']}**",
        "",
        "## Overall market-observation comparison",
        "",
        "| Metric | V13 historical | V14 shadow | Improvement (positive = V14 better) |",
        "|---|---:|---:|---:|",
        f"| Brier | {_fmt(overall['v13']['brier'])} | {_fmt(overall['v14']['brier'])} | {_fmt(overall['brier_improvement_v14_minus_v13'])} |",
        f"| Log Loss | {_fmt(overall['v13']['logloss'])} | {_fmt(overall['v14']['logloss'])} | {_fmt(overall['logloss_improvement_v14_minus_v13'])} |",
        f"| Accuracy @ 50% | {_fmt(overall['v13']['accuracy_at_50'])} | {_fmt(overall['v14']['accuracy_at_50'])} | — |",
        "",
        "## By market",
        "",
        "| Market | n | V13 Brier | V14 Brier | Δ Brier | V13 LogLoss | V14 LogLoss | Δ LogLoss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market, payload in report["by_market"].items():
        lines.append(f"| {market} | {payload['v13']['n']} | {_fmt(payload['v13']['brier'])} | {_fmt(payload['v14']['brier'])} | {_fmt(payload['brier_improvement_v14_minus_v13'])} | {_fmt(payload['v13']['logloss'])} | {_fmt(payload['v14']['logloss'])} | {_fmt(payload['logloss_improvement_v14_minus_v13'])} |")
    lines += [
        "",
        "## Interpretation",
        "",
        cov["interpretation"],
        "",
        "This report deliberately does not reconstruct missing player-level historical context from final-game data. Doing so would create look-ahead leakage and make the comparison invalid.",
    ]
    OUT_MD.write_text("\n".join(lines)+"\n", encoding="utf-8")


def main() -> None:
    report = build_report()
    write_report(report)
    print(json.dumps({
        "reference": report["reference"],
        "coverage": report["coverage"],
        "overall": report["overall"],
        "by_market": report["by_market"],
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
