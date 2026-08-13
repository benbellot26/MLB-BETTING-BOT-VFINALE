#!/usr/bin/env python3
"""V11.2 train-only selector over the leakage-safe V11.1 walk-forward rows.

The candidate deliberately removes the V11.1 bullpen/starter/matchup probability
corrections after they failed the historical holdout.  V11.2 learns only three
small correction terms from the first 75% of the chronological replay:

  * a global home-logit intercept;
  * relative projected-lineup strength versus each club's rolling regular lineup;
  * a regular-offense overlap correction to avoid duplicating offense already
    represented in the V10 baseline.

The final 25% is never used for coefficient selection.  This is research/shadow
only and cannot activate production automatically.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from statistics import mean

VERSION = "11.2-lineup-calibration-v1"
DEFAULT_INPUT = Path("data/v11_walkforward_2026.jsonl")
DEFAULT_REPORT = Path("data/v11_2_report.json")
DEFAULT_PREDICTIONS = Path("data/v11_2_predictions.jsonl")


def clamp(x, lo=.001, hi=.999):
    return max(lo, min(hi, float(x)))


def logit(p):
    p = clamp(p)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    z = max(-30.0, min(30.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def lineup_terms(row):
    f = row.get("features") or {}
    h = f.get("home_lineup_projected") or {}
    a = f.get("away_lineup_projected") or {}
    if not (h.get("available") and a.get("available")):
        return 0.0, 0.0, False
    try:
        h_lu = float(h["lineup_ops"]); h_reg = float(h["regular_ops"])
        a_lu = float(a["lineup_ops"]); a_reg = float(a["regular_ops"])
    except Exception:
        return 0.0, 0.0, False
    # 80 OPS points ~= one normalized lineup-strength unit.
    relative = ((h_lu - h_reg) - (a_lu - a_reg)) / .08
    regular_overlap = (h_reg - a_reg) / .08
    return relative, regular_overlap, True


def predict(row, params):
    base = clamp(row.get("base_p_home", .5))
    rel, regular, available = lineup_terms(row)
    if not available:
        rel = regular = 0.0
    z = logit(base)
    z += params["intercept"]
    z += params["relative_lineup_coef"] * rel
    z += params["regular_overlap_coef"] * regular
    return clamp(sigmoid(z)), rel, regular, available


def brier(rows, params=None):
    losses = []
    for r in rows:
        y = r.get("y")
        if y not in (0, 1):
            continue
        p = clamp(r.get("base_p_home", .5)) if params is None else predict(r, params)[0]
        losses.append((p - y) ** 2)
    return mean(losses) if losses else None


def logloss(rows, params=None):
    vals = []
    for r in rows:
        y = r.get("y")
        if y not in (0, 1):
            continue
        p = clamp(r.get("base_p_home", .5)) if params is None else predict(r, params)[0]
        vals.append(-(y * math.log(p) + (1-y) * math.log(1-p)))
    return mean(vals) if vals else None


def accuracy(rows, params=None):
    vals = []
    for r in rows:
        y = r.get("y")
        if y not in (0, 1):
            continue
        p = clamp(r.get("base_p_home", .5)) if params is None else predict(r, params)[0]
        vals.append(int((p >= .5) == bool(y)))
    return mean(vals) if vals else None


def bootstrap_gain(rows, params, reps=3000, seed=112):
    pairs = []
    for r in rows:
        y = r.get("y")
        if y not in (0, 1):
            continue
        pb = clamp(r.get("base_p_home", .5)); pn = predict(r, params)[0]
        pairs.append(((pb-y)**2, (pn-y)**2))
    if not pairs:
        return None
    rng = random.Random(seed); n = len(pairs); wins = 0
    for _ in range(reps):
        gain = 0.0
        for _ in range(n):
            b, v = pairs[rng.randrange(n)]
            gain += b-v
        wins += gain > 0
    return wins / reps


def frange(start, stop, step):
    n = int(round((stop-start)/step))
    return [round(start+i*step, 10) for i in range(n+1)]


def select_params(train):
    """Exhaustive small grid using TRAIN Brier only; no holdout access."""
    best = None
    base_b = brier(train)
    # Conservative bounded family.  Coefficients are logit-space corrections.
    for intercept in frange(-.02, .08, .005):
        for rel in frange(0.0, .15, .01):
            for overlap in frange(-.35, 0.0, .01):
                p = {
                    "intercept": intercept,
                    "relative_lineup_coef": rel,
                    "regular_overlap_coef": overlap,
                }
                score = brier(train, p)
                # Tiny deterministic simplicity penalty prevents meaningless edge ties.
                penalty = 1e-8 * (abs(intercept)/.005 + abs(rel)/.01 + abs(overlap)/.01)
                key = score + penalty
                if best is None or key < best[0]:
                    best = (key, score, p)
    assert best is not None
    params = best[2]
    return params, {"base_brier": base_b, "selected_brier": best[1], "brier_gain": base_b-best[1]}


def metrics(rows, params):
    bb = brier(rows); nb = brier(rows, params)
    bl = logloss(rows); nl = logloss(rows, params)
    return {
        "n": len(rows),
        "base_brier": bb,
        "v11_2_brier": nb,
        "brier_gain": None if bb is None or nb is None else bb-nb,
        "base_logloss": bl,
        "v11_2_logloss": nl,
        "logloss_gain": None if bl is None or nl is None else bl-nl,
        "base_accuracy": accuracy(rows),
        "v11_2_accuracy": accuracy(rows, params),
        "paired_gain_probability": bootstrap_gain(rows, params),
        "lineup_coverage": mean(1.0 if lineup_terms(r)[2] else 0.0 for r in rows) if rows else None,
    }


def self_test():
    row = {
        "base_p_home": .5, "y": 1,
        "features": {
            "home_lineup_projected": {"available": True, "lineup_ops": .800, "regular_ops": .740},
            "away_lineup_projected": {"available": True, "lineup_ops": .700, "regular_ops": .720},
        },
    }
    rel, reg, ok = lineup_terms(row)
    assert ok and rel > 0 and reg > 0
    params = {"intercept": 0, "relative_lineup_coef": .1, "regular_overlap_coef": 0}
    assert predict(row, params)[0] > .5
    print("SELF-TEST V11.2 SELECTOR OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--predictions", default=str(DEFAULT_PREDICTIONS))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test(); return

    rows = [json.loads(x) for x in Path(args.input).read_text(encoding="utf-8").splitlines() if x.strip()]
    rows.sort(key=lambda r: (r.get("game_date") or "", int(r.get("game_pk") or 0)))
    if len(rows) < 100:
        raise SystemExit("V11.2 requires a meaningful walk-forward sample")

    split = max(1, int(len(rows)*.75))
    train, holdout = rows[:split], rows[split:]
    params, train_selection = select_params(train)

    pred_rows = []
    for i, r in enumerate(rows):
        p, rel, regular, available = predict(r, params)
        pred_rows.append({
            "version": VERSION,
            "game_pk": r.get("game_pk"),
            "game_date": r.get("game_date"),
            "eastern_day": r.get("eastern_day"),
            "y": r.get("y"),
            "base_p_home": r.get("base_p_home"),
            "v11_2_p_home": round(p, 6),
            "relative_lineup_term": round(rel, 6),
            "regular_overlap_term": round(regular, 6),
            "lineup_available": available,
            "partition": "train" if i < split else "holdout",
            "official_effect": False,
            "no_lookahead": bool(r.get("no_lookahead")),
        })

    monthly = {}
    for r in rows:
        monthly.setdefault(str(r.get("eastern_day") or "")[:7], []).append(r)

    hold = metrics(holdout, params)
    report = {
        "version": VERSION,
        "created_from": str(args.input),
        "official_effect": False,
        "methodology": {
            "chronological_split": "first 75% train / final 25% holdout",
            "holdout_used_for_selection": False,
            "selected_on": "train Brier only",
            "candidate_family": "V10 logit + home intercept + relative projected-lineup delta + regular-offense overlap correction",
            "removed_from_candidate_probability": ["bullpen", "starter_recent", "matchup_lr"],
            "reason_removed": "V11.1 full-season holdout degradation",
            "live_confirmation_required": True,
            "historical_holdout_family_iteration_note": "The V11.2 family was designed after inspecting V11.1 aggregate results; live point-in-time confirmation remains mandatory.",
        },
        "selected_params": params,
        "train_selection": train_selection,
        "train": metrics(train, params),
        "holdout": hold,
        "all": metrics(rows, params),
        "monthly": {k: metrics(v, params) for k, v in sorted(monthly.items())},
        "gate": {
            "min_holdout_n": 300,
            "min_brier_gain": .0015,
            "min_gain_probability": .85,
            "logloss_no_worse": True,
            "candidate_better_than_v10": bool(
                hold.get("brier_gain") is not None and hold["brier_gain"] > 0
                and hold.get("logloss_gain") is not None and hold["logloss_gain"] >= 0
                and (hold.get("paired_gain_probability") or 0) >= .85
            ),
            "passes_full_production_evidence_gate": bool(
                len(holdout) >= 300
                and (hold.get("brier_gain") or -1) >= .0015
                and (hold.get("paired_gain_probability") or 0) >= .85
                and (hold.get("logloss_gain") or -1) >= 0
            ),
            "auto_activation": False,
        },
    }

    rp = Path(args.report); rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    pp = Path(args.predictions); pp.parent.mkdir(parents=True, exist_ok=True)
    with pp.open("w", encoding="utf-8") as fh:
        for r in pred_rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(json.dumps({
        "version": VERSION,
        "params": params,
        "train_gain": report["train"]["brier_gain"],
        "holdout_gain": hold["brier_gain"],
        "holdout_gain_probability": hold["paired_gain_probability"],
        "holdout_base_brier": hold["base_brier"],
        "holdout_v11_2_brier": hold["v11_2_brier"],
        "candidate_better_than_v10": report["gate"]["candidate_better_than_v10"],
        "passes_full_production_evidence_gate": report["gate"]["passes_full_production_evidence_gate"],
    }, indent=2))


if __name__ == "__main__":
    main()
