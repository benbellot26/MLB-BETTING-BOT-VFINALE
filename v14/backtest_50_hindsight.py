from __future__ import annotations

"""Deliberately biased 50-game hindsight comparison: V13 vs V14.

THIS IS NOT A VALID PREDICTIVE BACKTEST.

Both candidates are intentionally given information reconstructed after the
fact. Final boxscore identities are allowed, and V13 module weights are fitted
on the complete reconstructed sample including the target block. The purpose is
only to compare how the two model logics exploit a common hindsight context.
It must never be used as promotion evidence.
"""

from collections import defaultdict
import json
import math
from pathlib import Path
from typing import Any

from v11 import engine_v12 as engine
from v11 import v124_historical_reconstruction as hist
from v11 import v124_weight_optimizer as opt
from .context_overlay import context_overlay_from_feature_row
from .v13_context_adapter import adapt_feature_row

VALIDATION = Path("data/v13_historical_validation.json")
OUT_JSON = Path("data/v14_backtest_50_hindsight.json")
OUT_MD = Path("data/v14_backtest_50_hindsight.md")


def _num(v: Any, d: float | None = None) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _target_observations() -> tuple[list[dict[str, Any]], set[str]]:
    payload = json.loads(VALIDATION.read_text(encoding="utf-8"))
    rows = [r for r in payload.get("observations") or [] if isinstance(r, dict) and int(r.get("validation_block") or 0) == 0]
    rank = {"EARLY": 0, "LATE": 1, "FINAL": 2}
    best_phase: dict[str, str] = {}
    for row in rows:
        gid = str(row.get("game_pk") or "")
        phase = str(row.get("phase") or "EARLY").upper()
        if gid and (gid not in best_phase or rank.get(phase, -1) > rank.get(best_phase[gid], -1)):
            best_phase[gid] = phase
    canonical = [r for r in rows if str(r.get("phase") or "").upper() == best_phase.get(str(r.get("game_pk") or ""))]
    ids = {str(r.get("game_pk")) for r in canonical if r.get("game_pk") is not None}
    if len(ids) != int(payload.get("block_games") or 50):
        raise RuntimeError(f"expected 50 unique games, found {len(ids)}")
    return canonical, ids


def _context_results(source: list[dict[str, Any]], boxes: dict[str, Any], targets: set[str]) -> dict[str, dict[str, Any]]:
    """Build target contexts using final lineup identity and chronological state."""
    from v11.v124_statcast_provider import install as install_statcast
    install_statcast()
    state = hist.State()
    out: dict[str, dict[str, Any]] = {}
    for row in source:
        gid = str(row.get("game_pk") or "")
        box = boxes.get(gid)
        if not box:
            continue
        try:
            result = hist._build_result(row, box, state)
            if gid in targets:
                # Preserve the exact state used before this game's stats are added,
                # while allowing final boxscore identity (the intended bias).
                out[gid] = result
        finally:
            state.update(row, box)
    return out


def _hindsight_feature(result: dict[str, Any]) -> dict[str, Any]:
    ctx = json.loads(json.dumps(result.get("ctx") or {}))
    for side in ("home", "away"):
        starter = ctx.get(f"{side}_starter")
        if isinstance(starter, dict) and starter.get("inningsPitched") is None and starter.get("innings") is not None:
            starter["inningsPitched"] = starter.get("innings")
        lineup = ctx.get(f"{side}_lineup")
        if isinstance(lineup, dict):
            lineup["confirmed"] = True
            lineup["status"] = "FINAL_BOXSCORE_HINDSIGHT"
    row = {
        "schema": "v14-hindsight-feature-v1",
        "point_in_time": True,  # bypass only inside this explicitly leaky experiment
        "point_in_time_validation_reasons": [],
        "data_quality": {"eligible": True},
        "context": ctx,
        "features": json.loads(json.dumps(result.get("features") or {})),
        "rich_modules": {},
        "hindsight": True,
        "leakage_allowed_by_design": True,
    }
    return adapt_feature_row(row) or row


def _binary_probability(home: str, market: str, pick: str, point: Any, hmu: float, amu: float) -> tuple[float | None, float]:
    market = str(market or "").upper()
    pnt = _num(point)
    if market == "ML":
        ph = engine.prob_home_win(hmu, amu, dispersion=7.5, env_sigma=.08)
        return (ph if _norm(pick) == _norm(home) else 1.0-ph), 0.0
    if market == "RUNLINE" and pnt is not None:
        side = "home" if _norm(pick) == _norm(home) else "away"
        win, push = engine.prob_cover_parts(hmu, amu, side, pnt, dispersion=7.5, env_sigma=.08)
        return win / max(1e-9, 1.0-push), push
    if market == "TOTAL" and pnt is not None:
        side = "over" if str(pick).lower() == "over" else "under"
        win, push = engine.prob_total_parts(hmu, amu, side, pnt, dispersion=7.5, env_sigma=.08)
        return win / max(1e-9, 1.0-push), push
    return None, 0.0


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    use = [r for r in rows if r.get("result") in {"WIN", "LOSS"} and _num(r.get(key)) is not None]
    if not use:
        return {"n": 0, "brier": None, "logloss": None, "accuracy": None}
    probs = [max(.001, min(.999, float(r[key]))) for r in use]
    ys = [1.0 if r["result"] == "WIN" else 0.0 for r in use]
    brier = sum((p-y)**2 for p, y in zip(probs, ys))/len(use)
    ll = -sum(y*math.log(p)+(1-y)*math.log(1-p) for p, y in zip(probs, ys))/len(use)
    acc = sum((p >= .5) == bool(y) for p, y in zip(probs, ys))/len(use)
    return {"n": len(use), "brier": brier, "logloss": ll, "accuracy": acc, "mean_probability": sum(probs)/len(probs)}


def _result_from_validation(obs: dict[str, Any]) -> str | None:
    value = obs.get("settled_result") or obs.get("result")
    if value in {"WIN", "LOSS", "PUSH"}:
        return value
    return None


def build() -> dict[str, Any]:
    observations, target_ids = _target_observations()
    source_all = hist._load_rows()
    target_source = [r for r in source_all if str(r.get("game_pk")) in target_ids]
    if not target_source:
        raise RuntimeError("none of the 50 reference games found in historical reconstruction source")
    max_day = max(str(r.get("game_date") or "") for r in target_source)
    # Keep all earlier rows so reconstructed player/bullpen state includes history.
    source = [r for r in source_all if str(r.get("game_date") or "") <= max_day]
    boxes, box_failures = hist._prefetch_boxes(source)
    reconstructed, recon_failures = hist.reconstruct(source, boxes, use_statcast=True)
    examples = opt.examples(reconstructed)
    if len(examples) < opt.MIN_GAMES:
        raise RuntimeError(f"insufficient reconstructed examples: {len(examples)}")

    # Deliberate hindsight fitting: use the complete reconstructed set including targets.
    weights = opt.fit_weights(examples)
    by_game = {str(ex.get("game_pk")): ex for ex in examples}
    contexts = _context_results(source, boxes, target_ids)

    evaluated: list[dict[str, Any]] = []
    v13_games = v14_games = 0
    deltas = []
    for obs in observations:
        gid = str(obs.get("game_pk") or "")
        ex = by_game.get(gid)
        ctx_result = contexts.get(gid)
        if not ex or not ctx_result:
            continue
        h13, a13, hf, af = opt._weighted_runs(ex, weights)
        v13_games += 1
        feature = _hindsight_feature(ctx_result)
        overlay = context_overlay_from_feature_row(feature, h13, a13)
        h14, a14 = float(overlay["home_mu"]), float(overlay["away_mu"])
        if abs(h14-h13) > 1e-12 or abs(a14-a13) > 1e-12:
            v14_games += 1
        home = str((ctx_result.get("ctx") or {}).get("home") or "")
        p13, push13 = _binary_probability(home, obs.get("market"), obs.get("pick"), obs.get("point"), h13, a13)
        p14, push14 = _binary_probability(home, obs.get("market"), obs.get("pick"), obs.get("point"), h14, a14)
        if p13 is None or p14 is None:
            continue
        deltas.append(p14-p13)
        evaluated.append({
            "game_pk": gid,
            "market": str(obs.get("market") or "").upper(),
            "pick": obs.get("pick"),
            "point": obs.get("point"),
            "result": _result_from_validation(obs),
            "v13_hindsight_probability": p13,
            "v14_hindsight_probability": p14,
            "probability_delta": p14-p13,
            "v13_home_mu": h13,
            "v13_away_mu": a13,
            "v14_home_mu": h14,
            "v14_away_mu": a14,
            "v13_weighted_factor_home": hf,
            "v13_weighted_factor_away": af,
            "v14_home_context_delta": overlay.get("home_delta"),
            "v14_away_context_delta": overlay.get("away_delta"),
            "v14_components": overlay.get("components"),
            "push13": push13,
            "push14": push14,
        })

    overall13 = _metrics(evaluated, "v13_hindsight_probability")
    overall14 = _metrics(evaluated, "v14_hindsight_probability")
    by_market = {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        rows = [r for r in evaluated if r["market"] == market]
        a = _metrics(rows, "v13_hindsight_probability")
        b = _metrics(rows, "v14_hindsight_probability")
        by_market[market] = {
            "v13": a,
            "v14": b,
            "brier_gain_v14": None if a["brier"] is None or b["brier"] is None else a["brier"]-b["brier"],
            "logloss_gain_v14": None if a["logloss"] is None or b["logloss"] is None else a["logloss"]-b["logloss"],
        }

    report = {
        "schema": "v14-50-game-hindsight-biased-v1",
        "valid_predictive_backtest": False,
        "production_promotion_evidence": False,
        "warning": "Deliberately leaky hindsight experiment. Final boxscore lineup/starter identity is permitted; V13 module weights are fit on the complete reconstructed sample including target games.",
        "fairness": "Both V13 and V14 receive the same hindsight identity/state reconstruction. V14 then adds only its contextual residual layer.",
        "reference_unique_games": len(target_ids),
        "target_games_found_in_reconstruction": len({str(r.get('game_pk')) for r in target_source}),
        "reconstruction_games_used_for_hindsight_fit": len(examples),
        "boxscore_failures": len(box_failures),
        "reconstruction_failures": len(recon_failures),
        "v13_hindsight_weights": weights,
        "v13_games_evaluated": len({r["game_pk"] for r in evaluated}),
        "v14_context_changed_games": len({r["game_pk"] for r in evaluated if abs(r["v14_home_mu"]-r["v13_home_mu"]) > 1e-12 or abs(r["v14_away_mu"]-r["v13_away_mu"]) > 1e-12}),
        "overall": {
            "v13": overall13,
            "v14": overall14,
            "brier_gain_v14": overall13["brier"]-overall14["brier"] if overall13["brier"] is not None and overall14["brier"] is not None else None,
            "logloss_gain_v14": overall13["logloss"]-overall14["logloss"] if overall13["logloss"] is not None and overall14["logloss"] is not None else None,
            "mean_probability_delta_v14_minus_v13": sum(deltas)/len(deltas) if deltas else None,
            "max_abs_probability_delta": max((abs(x) for x in deltas), default=None),
        },
        "by_market": by_market,
        "rows": evaluated,
    }
    return report


def _fmt(x: Any, d: int = 6) -> str:
    return "n/a" if x is None else f"{x:.{d}f}" if isinstance(x, float) else str(x)


def write(report: dict[str, Any]) -> None:
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    o = report["overall"]
    lines = [
        "# Pulsar V13 vs V14 — 50-game HINDSIGHT / BIASED experiment",
        "",
        "> **WARNING:** deliberately leaky. Not predictive evidence and not a promotion gate.",
        "",
        f"Reference games: **{report['reference_unique_games']}**",
        f"Target games evaluated: **{report['v13_games_evaluated']}**",
        f"Historical games used to fit hindsight V13 weights: **{report['reconstruction_games_used_for_hindsight_fit']}**",
        f"Games where V14 changed the hindsight V13 run means: **{report['v14_context_changed_games']}**",
        "",
        "## Overall",
        "",
        "| Metric | V13 hindsight | V14 hindsight | Gain V14 (positive = better) |",
        "|---|---:|---:|---:|",
        f"| Brier | {_fmt(o['v13']['brier'])} | {_fmt(o['v14']['brier'])} | {_fmt(o['brier_gain_v14'])} |",
        f"| Log Loss | {_fmt(o['v13']['logloss'])} | {_fmt(o['v14']['logloss'])} | {_fmt(o['logloss_gain_v14'])} |",
        f"| Accuracy @50% | {_fmt(o['v13']['accuracy'])} | {_fmt(o['v14']['accuracy'])} | — |",
        "",
        "## By market",
        "",
        "| Market | n | V13 Brier | V14 Brier | Gain | V13 LogLoss | V14 LogLoss | Gain |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market, p in report["by_market"].items():
        lines.append(f"| {market} | {p['v13']['n']} | {_fmt(p['v13']['brier'])} | {_fmt(p['v14']['brier'])} | {_fmt(p['brier_gain_v14'])} | {_fmt(p['v13']['logloss'])} | {_fmt(p['v14']['logloss'])} | {_fmt(p['logloss_gain_v14'])} |")
    lines += ["", "## Hindsight V13 weights", "", "```json", json.dumps(report["v13_hindsight_weights"], indent=2, sort_keys=True), "```", "", report["warning"], ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build()
    write(report)
    print(json.dumps({k: report[k] for k in ("schema", "valid_predictive_backtest", "reference_unique_games", "target_games_found_in_reconstruction", "reconstruction_games_used_for_hindsight_fit", "boxscore_failures", "reconstruction_failures", "v13_hindsight_weights", "v13_games_evaluated", "v14_context_changed_games", "overall", "by_market")}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
