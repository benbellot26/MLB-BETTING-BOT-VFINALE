from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from . import config, pro_model, storage
from .journal import load_rows


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _canonical(rows, phase=None):
    if phase is None:
        return pro_model.canonical_settled_rows(rows)
    best = {}
    for r in rows:
        if r.get("bet_type") == "COMBO" or r.get("result_status") != "FINAL" or not r.get("game_pk") or not r.get("options"):
            continue
        if str(r.get("phase") or "").upper() != phase:
            continue
        analyzed, game_time = _dt(r.get("analyzed_at")), _dt(r.get("game_date"))
        if not analyzed or not game_time or analyzed >= game_time:
            continue
        gid, rank = str(r.get("game_pk")), str(r.get("analyzed_at") or "")
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, r)
    return [x[1] for x in best.values()]


def _binary_metrics(ps, ys):
    if not ps:
        return {"n": 0}
    n = len(ps)
    return {
        "n": n,
        "accuracy": sum((p >= .5) == bool(y) for p, y in zip(ps, ys))/n,
        "brier": sum((p-y)**2 for p, y in zip(ps, ys))/n,
        "logloss": sum(-(y*math.log(max(.001, min(.999, p)))+(1-y)*math.log(max(.001, min(.999, 1-p)))) for p, y in zip(ps, ys))/n,
    }


def _market(rows, market):
    chosen = []
    for r in rows:
        o = pro_model.canonical_market_option(r, market)
        if o and o.get("result") in {"WIN", "LOSS"}:
            chosen.append(o)
    if not chosen:
        return {"n": 0}
    ys = [1 if o.get("result") == "WIN" else 0 for o in chosen]
    effective = [_num(o.get("p_effective"), .5) for o in chosen]
    pre_cal = [_num(o.get("p_model"), .5) for o in chosen]
    structural = [_num(o.get("p_structural"), .5) for o in chosen]
    sharp = [(o.get("p_market"), y) for o, y in zip(chosen, ys) if o.get("p_market") is not None]
    out = {
        "n": len(chosen),
        "model": _binary_metrics(effective, ys),
        "precalibration": _binary_metrics(pre_cal, ys),
        "structural": _binary_metrics(structural, ys),
        "sharp": _binary_metrics([_num(p, .5) for p, _ in sharp], [y for _, y in sharp]),
        "calibration_bins": [],
        "selection": "one canonical main line per game; no alternate-line cherry-picking",
    }
    for lo in (.50, .55, .60, .65, .70, .75):
        hi = 1.01 if lo == .75 else lo+.05
        z = [(p, y) for p, y in zip(effective, ys) if lo <= p < hi]
        if z:
            out["calibration_bins"].append({
                "bin": f"{int(lo*100)}-{100 if hi > 1 else int(hi*100)}%",
                "n": len(z), "avg_probability": sum(p for p, _ in z)/len(z),
                "hit_rate": sum(y for _, y in z)/len(z),
            })
    return out


def _future_residual_metrics(block, candidate):
    if not block:
        return {"n": 0}
    model = dict(candidate)
    model["active"] = True
    base_err, cand_err = [], []
    for r in block:
        bh, ba = pro_model.base_runs(r)
        if bh is None or ba is None:
            continue
        ch, ca, _ = pro_model.apply_run_correction(bh, ba, r, model)
        hs, aps = _num(r.get("home_score")), _num(r.get("away_score"))
        base_err += [(bh-hs)**2, (ba-aps)**2]
        cand_err += [(ch-hs)**2, (ca-aps)**2]
    if not base_err:
        return {"n": 0}
    b = math.sqrt(sum(base_err)/len(base_err))
    c = math.sqrt(sum(cand_err)/len(cand_err))
    return {"n": len(base_err)//2, "base_rmse": b, "candidate_rmse": c, "rmse_gain": b-c}


def _future_calibration_metrics(block, candidate, market):
    model = dict(candidate)
    model["active"] = True
    base, cand, ys = [], [], []
    for r in block:
        a, b = pro_model.canonical_market_pair(r, market)
        if not a or not b or a.get("result") not in {"WIN", "LOSS"}:
            continue
        p1 = _num(a.get("p_model", a.get("p_effective")), .5)
        p2 = _num(b.get("p_model", b.get("p_effective")), 1-p1)
        q1, _, _, _ = pro_model.calibrate_pair(market, p1, p2, model)
        base.append(p1)
        cand.append(q1)
        ys.append(1 if a.get("result") == "WIN" else 0)
    mb, mc = _binary_metrics(base, ys), _binary_metrics(cand, ys)
    return {
        "n": len(ys), "base": mb, "candidate": mc,
        "brier_gain": (mb.get("brier", 0)-mc.get("brier", 0)) if ys else None,
        "logloss_gain": (mb.get("logloss", 0)-mc.get("logloss", 0)) if ys else None,
    }


def _walk_forward(rows, step=50):
    ordered = sorted(pro_model.canonical_settled_rows(rows), key=lambda r: str(r.get("game_date") or r.get("analyzed_at") or ""))
    checks = []
    start = max(config.MIN_RESIDUAL_TRAIN_GAMES, config.MIN_CALIBRATION_GAMES, config.MIN_DISPERSION_TRAIN_GAMES)
    for end in range(start, len(ordered), step):
        prefix = ordered[:end]
        future = ordered[end:min(len(ordered), end+step)]
        if not future:
            continue
        c = pro_model.build_candidate(prefix)
        d = c.get("dispersion") or {}
        base_nll = pro_model._run_nll(future, config.RUN_DISPERSION)
        cand_nll = pro_model._run_nll(future, d.get("value", config.RUN_DISPERSION)) if d.get("active") else base_nll
        checks.append({
            "trained_games": len(prefix),
            "future_games": len(future),
            "through": prefix[-1].get("game_date"),
            "future_through": future[-1].get("game_date"),
            "candidate_internal_passes": c.get("passes"),
            "residual_future": _future_residual_metrics(future, c),
            "dispersion_future": {
                "active": bool(d.get("active")), "value": d.get("value"),
                "base_nll": base_nll, "candidate_nll": cand_nll,
                "nll_gain": (base_nll-cand_nll) if base_nll is not None and cand_nll is not None else None,
            },
            "calibration_future": {m: _future_calibration_metrics(future, c, m) for m in ("ML", "RUNLINE", "TOTAL")},
        })
    return checks


def build_report(rows=None):
    rows = load_rows() if rows is None else rows
    phases = {}
    for phase in ("EARLY", "LATE", "FINAL"):
        xs = _canonical(rows, phase)
        phases[phase] = {"games": len(xs), "markets": {m: _market(xs, m) for m in ("ML", "RUNLINE", "TOTAL")}}
    all_rows = _canonical(rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": config.VERSION,
        "methodology": {
            "point_in_time_only": True, "strictly_pregame_rows": True,
            "one_snapshot_per_game_for_training": True,
            "canonical_market_line": True, "phase_separated": True,
            "historical_odds_fabricated": False, "true_future_block_walk_forward": True,
            "claim_limit": "Full historical engine replay requires archived point-in-time source payloads; absent observations are never reconstructed from future data.",
        },
        "all": {"games": len(all_rows), "markets": {m: _market(all_rows, m) for m in ("ML", "RUNLINE", "TOTAL")}},
        "phases": phases,
        "walk_forward": _walk_forward(rows),
        "betting": storage.ledger_summary(),
    }


def write_report(path="data/v11_point_in_time_backtest.json"):
    rep = build_report()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return rep


if __name__ == "__main__":
    print(json.dumps(write_report(), ensure_ascii=False, indent=2, sort_keys=True))
