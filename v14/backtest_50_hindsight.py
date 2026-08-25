from __future__ import annotations

"""Deliberately leaky 50-game V13-vs-V14 hindsight experiment.

NOT predictive evidence. Both versions are allowed to see final boxscore
identity and same-game player performance. V13 context weights are then fitted
on the same 50 target games. This is intentionally biased by user request and
exists only as a relative stress test of the two logics.
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
BACKFILL = Path("data/v13_historical_backfill.jsonl")
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


def _jsonl(path: Path) -> list[dict[str, Any]]:
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


def _canonical_observations() -> tuple[list[dict[str, Any]], set[str]]:
    payload = json.loads(VALIDATION.read_text(encoding="utf-8"))
    rows = [r for r in payload.get("observations") or [] if isinstance(r, dict) and int(r.get("validation_block") or 0) == 0]
    phase_rank = {"EARLY": 0, "LATE": 1, "FINAL": 2}
    best: dict[str, str] = {}
    for r in rows:
        gid = str(r.get("game_pk") or "")
        phase = str(r.get("phase") or "EARLY").upper()
        if gid and (gid not in best or phase_rank.get(phase, -1) > phase_rank.get(best[gid], -1)):
            best[gid] = phase
    out = [r for r in rows if str(r.get("phase") or "").upper() == best.get(str(r.get("game_pk") or ""))]
    ids = {str(r.get("game_pk")) for r in out if r.get("game_pk") is not None}
    if len(ids) != int(payload.get("block_games") or 50):
        raise RuntimeError(f"expected 50 games, found {len(ids)}")
    return out, ids


def _best_backfill(ids: set[str]) -> dict[str, dict[str, Any]]:
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for r in _jsonl(BACKFILL):
        gid = str(r.get("game_pk") or "")
        if gid not in ids:
            continue
        key = str(r.get("analyzed_at") or "")
        if gid not in best or key > best[gid][0]:
            best[gid] = (key, r)
    return {gid: r for gid, (_k, r) in best.items()}


def _starter_id(box: dict[str, Any], side: str) -> Any:
    pitchers = (((box.get("teams") or {}).get(side) or {}).get("pitchers") or [])
    return pitchers[0] if pitchers else None


def _team_name(box: dict[str, Any], side: str, fallback: str) -> str:
    return str(((((box.get("teams") or {}).get(side) or {}).get("team") or {}).get("name")) or fallback)


def _score_from_box(box: dict[str, Any], side: str) -> int:
    team_stats = (((box.get("teams") or {}).get(side) or {}).get("teamStats") or {}).get("batting") or {}
    runs = _num(team_stats.get("runs"))
    return int(runs or 0)


def _synthetic_row(gid: str, box: dict[str, Any], backfill: dict[str, Any]) -> dict[str, Any]:
    home = str(backfill.get("home") or _team_name(box, "home", "Home"))
    away = str(backfill.get("away") or _team_name(box, "away", "Away"))
    return {
        "game_pk": int(gid),
        "game_date": backfill.get("game_date") or backfill.get("target_date") or "2026-01-01T00:00:00+00:00",
        "home": home,
        "away": away,
        "home_score": _score_from_box(box, "home"),
        "away_score": _score_from_box(box, "away"),
        "starters": {
            "home_id": _starter_id(box, "home"),
            "away_id": _starter_id(box, "away"),
            "home_hand": "R",
            "away_hand": "R",
        },
        "league": {"ops": .710, "era": 4.35},
        "v10": {
            "home_struct": _num(backfill.get("projected_home_runs"), 4.4),
            "away_struct": _num(backfill.get("projected_away_runs"), 4.2),
        },
    }


def _same_game_hindsight(row: dict[str, Any], box: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Leak current game's own stats into the context before predicting it."""
    state = hist.State()
    state.update(row, box)  # intentional same-game leakage
    result = hist._build_result(row, box, state)
    modules = hist._modules(result, row, state, use_statcast=False)
    return result, modules


def _settled_option(obs: dict[str, Any]) -> str | None:
    value = obs.get("settled_result") or obs.get("result")
    return value if value in {"WIN", "LOSS", "PUSH"} else None


def _hist_options(observations: list[dict[str, Any]], gid: str) -> list[dict[str, Any]]:
    # Optimizer training uses only ML/RL because its historical variant helper
    # natively supports those markets. Totals are still evaluated afterwards.
    out = []
    for obs in observations:
        if str(obs.get("game_pk")) != gid:
            continue
        market = str(obs.get("market") or "").upper()
        if market not in {"ML", "RUNLINE"}:
            continue
        result = _settled_option(obs)
        if result not in {"WIN", "LOSS"}:
            continue
        out.append({"market": market, "name": obs.get("pick"), "point": obs.get("point"), "result": result})
    return out


def _reconstructed_row(row: dict[str, Any], result: dict[str, Any], modules: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    h = max(1.6, min(8.0, float((row.get("v10") or {}).get("home_struct") or 4.4)))
    a = max(1.6, min(8.0, float((row.get("v10") or {}).get("away_struct") or 4.2)))
    variants = {"baseline_v1232": {"home_mu": h, "away_mu": a, "options": hist._variant_options(result, h, a)}}
    for name in opt.MODULES:
        mod = modules.get(name) or {}
        hf = max(.80, min(1.20, float(_num(mod.get("home_factor"), 1.0) or 1.0)))
        af = max(.80, min(1.20, float(_num(mod.get("away_factor"), 1.0) or 1.0)))
        variants[f"only_{name}"] = {
            "home_mu": h*hf, "away_mu": a*af,
            "home_factor": hf, "away_factor": af,
            "options": hist._variant_options(result, h*hf, a*af),
        }
    return {
        "game_pk": row["game_pk"], "game_date": row["game_date"],
        "home_score": row["home_score"], "away_score": row["away_score"],
        "options": _hist_options(observations, str(row["game_pk"])),
        "shadow_v124": {"enabled": True, "status": "HINDSIGHT_LEAKY", "base_home_mu": h, "base_away_mu": a, "modules": modules, "variants": variants},
    }


def _feature(result: dict[str, Any]) -> dict[str, Any]:
    ctx = json.loads(json.dumps(result.get("ctx") or {}))
    for side in ("home", "away"):
        starter = ctx.get(f"{side}_starter")
        if isinstance(starter, dict) and starter.get("inningsPitched") is None and starter.get("innings") is not None:
            starter["inningsPitched"] = starter.get("innings")
        lineup = ctx.get(f"{side}_lineup")
        if isinstance(lineup, dict):
            lineup["confirmed"] = True
            lineup["status"] = "FINAL_BOXSCORE_HINDSIGHT"
    raw = {
        "point_in_time": True,
        "point_in_time_validation_reasons": [],
        "data_quality": {"eligible": True},
        "context": ctx,
        "features": json.loads(json.dumps(result.get("features") or {})),
        "rich_modules": {},
        "hindsight": True,
    }
    return adapt_feature_row(raw) or raw


def _prob(home: str, market: str, pick: str, point: Any, hmu: float, amu: float) -> float | None:
    market = str(market or "").upper(); pnt = _num(point)
    if market == "ML":
        ph = engine.prob_home_win(hmu, amu, dispersion=7.5, env_sigma=.08)
        return ph if _norm(pick) == _norm(home) else 1-ph
    if market == "RUNLINE" and pnt is not None:
        side = "home" if _norm(pick) == _norm(home) else "away"
        w, push = engine.prob_cover_parts(hmu, amu, side, pnt, dispersion=7.5, env_sigma=.08)
        return w/max(1e-9, 1-push)
    if market == "TOTAL" and pnt is not None:
        side = "over" if str(pick).lower() == "over" else "under"
        w, push = engine.prob_total_parts(hmu, amu, side, pnt, dispersion=7.5, env_sigma=.08)
        return w/max(1e-9, 1-push)
    return None


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    use = [r for r in rows if r.get("result") in {"WIN", "LOSS"} and _num(r.get(key)) is not None]
    if not use: return {"n": 0, "brier": None, "logloss": None, "accuracy": None}
    ps = [max(.001, min(.999, float(r[key]))) for r in use]
    ys = [1.0 if r["result"] == "WIN" else 0.0 for r in use]
    return {
        "n": len(use),
        "brier": sum((p-y)**2 for p,y in zip(ps,ys))/len(use),
        "logloss": -sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/len(use),
        "accuracy": sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/len(use),
        "mean_probability": sum(ps)/len(ps),
    }


def build() -> dict[str, Any]:
    observations, ids = _canonical_observations()
    backfill = _best_backfill(ids)
    boxes, failures = hist._prefetch_boxes([{"game_pk": int(g)} for g in sorted(ids)])

    rec_rows = []
    contexts: dict[str, dict[str, Any]] = {}
    raw_rows: dict[str, dict[str, Any]] = {}
    for gid in sorted(ids):
        box = boxes.get(gid); bf = backfill.get(gid)
        if not box or not bf: continue
        row = _synthetic_row(gid, box, bf)
        result, modules = _same_game_hindsight(row, box)
        rec_rows.append(_reconstructed_row(row, result, modules, observations))
        contexts[gid] = result
        raw_rows[gid] = row

    exs = opt.examples(rec_rows)
    # Deliberate target leakage: allow fitting with fewer than the normal 75 and
    # fit on the target games themselves.
    old_min = opt.MIN_GAMES
    try:
        opt.MIN_GAMES = 1
        weights = opt.fit_weights(exs)
    finally:
        opt.MIN_GAMES = old_min
    ex_by_gid = {str(ex.get("game_pk")): ex for ex in exs}

    evaluated = []
    changed = set()
    for obs in observations:
        gid = str(obs.get("game_pk") or "")
        ex = ex_by_gid.get(gid); result = contexts.get(gid); row = raw_rows.get(gid)
        if not ex or not result or not row: continue
        h13, a13, _hf, _af = opt._weighted_runs(ex, weights)
        overlay = context_overlay_from_feature_row(_feature(result), h13, a13)
        h14, a14 = float(overlay["home_mu"]), float(overlay["away_mu"])
        if abs(h14-h13)>1e-12 or abs(a14-a13)>1e-12: changed.add(gid)
        p13 = _prob(row["home"], obs.get("market"), obs.get("pick"), obs.get("point"), h13, a13)
        p14 = _prob(row["home"], obs.get("market"), obs.get("pick"), obs.get("point"), h14, a14)
        if p13 is None or p14 is None: continue
        evaluated.append({
            "game_pk": gid, "market": str(obs.get("market") or "").upper(), "pick": obs.get("pick"), "point": obs.get("point"),
            "result": _settled_option(obs), "v13_hindsight_probability": p13, "v14_hindsight_probability": p14,
            "probability_delta": p14-p13, "v13_home_mu": h13, "v13_away_mu": a13, "v14_home_mu": h14, "v14_away_mu": a14,
            "v14_home_context_delta": overlay.get("home_delta"), "v14_away_context_delta": overlay.get("away_delta"), "v14_components": overlay.get("components"),
        })

    m13 = _metrics(evaluated, "v13_hindsight_probability"); m14 = _metrics(evaluated, "v14_hindsight_probability")
    by_market = {}
    for market in ("ML","RUNLINE","TOTAL"):
        rs=[r for r in evaluated if r["market"]==market]; a=_metrics(rs,"v13_hindsight_probability"); b=_metrics(rs,"v14_hindsight_probability")
        by_market[market]={"v13":a,"v14":b,"brier_gain_v14":None if a["brier"] is None or b["brier"] is None else a["brier"]-b["brier"],"logloss_gain_v14":None if a["logloss"] is None or b["logloss"] is None else a["logloss"]-b["logloss"]}
    deltas=[r["probability_delta"] for r in evaluated]
    return {
        "schema":"v14-50-game-hindsight-biased-v2","valid_predictive_backtest":False,"production_promotion_evidence":False,
        "warning":"MAXIMUM LEAKAGE BY DESIGN: final lineup/starter identity and the current game's own player performance are visible to both models; V13 context weights are fitted on the target games themselves.",
        "reference_games":len(ids),"boxscores_loaded":len(boxes),"boxscore_failures":len(failures),"backfill_games":len(backfill),"optimizer_examples":len(exs),"v13_hindsight_weights":weights,
        "evaluated_unique_games":len({r["game_pk"] for r in evaluated}),"v14_context_changed_games":len(changed),
        "overall":{"v13":m13,"v14":m14,"brier_gain_v14":None if m13["brier"] is None or m14["brier"] is None else m13["brier"]-m14["brier"],"logloss_gain_v14":None if m13["logloss"] is None or m14["logloss"] is None else m13["logloss"]-m14["logloss"],"mean_probability_delta":sum(deltas)/len(deltas) if deltas else None,"max_abs_probability_delta":max((abs(x) for x in deltas),default=None)},
        "by_market":by_market,"rows":evaluated,
    }


def _fmt(x: Any) -> str:
    return "n/a" if x is None else f"{x:.6f}" if isinstance(x,float) else str(x)


def write(report: dict[str, Any]) -> None:
    OUT_JSON.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    o=report["overall"]
    lines=["# Pulsar V13 vs V14 — 50-game MAXIMUM-HINDSIGHT experiment","","> **Deliberately biased. Never use as production/promotion evidence.**","",f"Reference games: **{report['reference_games']}**",f"Boxscores loaded: **{report['boxscores_loaded']}**",f"Games evaluated: **{report['evaluated_unique_games']}**",f"Games changed by V14 context: **{report['v14_context_changed_games']}**","","| Metric | V13 hindsight | V14 hindsight | V14 gain |","|---|---:|---:|---:|",f"| Brier | {_fmt(o['v13']['brier'])} | {_fmt(o['v14']['brier'])} | {_fmt(o['brier_gain_v14'])} |",f"| LogLoss | {_fmt(o['v13']['logloss'])} | {_fmt(o['v14']['logloss'])} | {_fmt(o['logloss_gain_v14'])} |",f"| Accuracy | {_fmt(o['v13']['accuracy'])} | {_fmt(o['v14']['accuracy'])} | — |","","## By market","","| Market | n | V13 Brier | V14 Brier | Gain | V13 LogLoss | V14 LogLoss | Gain |","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for m,p in report["by_market"].items(): lines.append(f"| {m} | {p['v13']['n']} | {_fmt(p['v13']['brier'])} | {_fmt(p['v14']['brier'])} | {_fmt(p['brier_gain_v14'])} | {_fmt(p['v13']['logloss'])} | {_fmt(p['v14']['logloss'])} | {_fmt(p['logloss_gain_v14'])} |")
    lines += ["","## V13 hindsight-fitted weights","","```json",json.dumps(report["v13_hindsight_weights"],indent=2,sort_keys=True),"```","",report["warning"],""]
    OUT_MD.write_text("\n".join(lines),encoding="utf-8")


def main() -> None:
    report=build(); write(report)
    print(json.dumps({k:report[k] for k in ("schema","valid_predictive_backtest","reference_games","boxscores_loaded","boxscore_failures","backfill_games","optimizer_examples","v13_hindsight_weights","evaluated_unique_games","v14_context_changed_games","overall","by_market")},ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__": main()
