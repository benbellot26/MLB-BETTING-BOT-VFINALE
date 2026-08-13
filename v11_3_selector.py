#!/usr/bin/env python3
"""V11.3 non-regression selector.

V11.2 remains the probability engine.  The V11.3 residual model is used only
as a research confidence/ranking layer unless it independently beats V11.2 on
Brier + LogLoss.  This prevents a higher raw accuracy target from degrading
probability quality.

The selector never auto-activates production and never learns from the final
holdout when choosing model coefficients.  A 0.56 residual-certainty band is
reported as a research band only and requires live point-in-time confirmation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import v11_3_residual_lab as lab

VERSION = "11.3-selector-v1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/v11_walkforward_2026.jsonl")
    ap.add_argument("--v112-report", default="data/v11_2_report.json")
    ap.add_argument("--output", default="data/v11_3_selector_report.json")
    ap.add_argument("--research-certainty", type=float, default=.56)
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.input).read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r.get("y") in (0, 1) and r.get("base_p_home") is not None]
    rows.sort(key=lambda r: (r.get("game_date") or "", int(r.get("game_pk") or 0)))
    split = int(len(rows) * .75)
    train, holdout = rows[:split], rows[split:]

    v112_rep = json.loads(Path(args.v112_report).read_text(encoding="utf-8"))
    params = v112_rep["selected_params"]
    v112_fn = lambda r: lab.v112_predict(r, params)

    # Family + regularization are selected from development-sample chronological
    # OOF accuracy only.  The holdout is not consulted for this choice.
    candidates = []
    for set_name, names in lab.FEATURE_SETS.items():
        for l2 in (.5, 2.0, 8.0, 32.0, 128.0, 512.0):
            cv = lab.cv_candidate(train, names, l2)
            if not cv:
                continue
            threshold, directional_acc = lab.choose_decision_threshold(cv["oof"])
            candidates.append({
                "feature_set": set_name,
                "features": names,
                "l2": l2,
                "cv_brier": cv["cv_brier"],
                "cv_logloss": cv["cv_logloss"],
                "cv_accuracy_050": cv["cv_accuracy"],
                "cv_direction_threshold": threshold,
                "cv_direction_accuracy": directional_acc,
            })

    selected = max(
        candidates,
        key=lambda x: (
            x["cv_direction_accuracy"],
            -x["cv_brier"],
            -x["cv_logloss"],
            -len(x["features"]),
        ),
    )
    model = lab.fit_model(train, selected["features"], selected["l2"])
    residual_fn = lambda r: lab.predict_model(r, model)

    m112 = lab.metrics(holdout, v112_fn)
    mres = lab.metrics(holdout, residual_fn)
    mdir = lab.metrics(holdout, residual_fn, threshold=selected["cv_direction_threshold"])
    mstrong = lab.strong_metrics(holdout, residual_fn, args.research_certainty)

    # Probability engine may change only if the residual candidate improves both
    # proper scoring rules.  Otherwise V11.2 is retained automatically.
    residual_probability_pass = bool(
        mres["brier"] < m112["brier"] and mres["logloss"] < m112["logloss"]
    )
    probability_engine = "V11.3 residual" if residual_probability_pass else "V11.2"

    report = {
        "version": VERSION,
        "official_effect": False,
        "auto_activation": False,
        "samples": {"all": len(rows), "development": len(train), "holdout": len(holdout)},
        "selection_contract": {
            "feature_and_l2_selected_on": "development expanding-window chronological CV only",
            "holdout_used_for_model_selection": False,
            "holdout_used_for_probability_promotion": True,
            "probability_non_regression_rule": "residual must beat V11.2 on both Brier and LogLoss",
            "research_certainty_band": args.research_certainty,
            "research_band_is_production_threshold": False,
            "live_confirmation_required": True,
        },
        "selected_residual": selected,
        "holdout": {
            "v11_2_probability": m112,
            "residual_probability": mres,
            "residual_directional": mdir,
            "research_strong_band": mstrong,
        },
        "decision": {
            "probability_engine": probability_engine,
            "residual_probability_pass": residual_probability_pass,
            "selector_role": "confidence/ranking research only" if not residual_probability_pass else "candidate probability + confidence research",
        },
        "targets": {
            "all_match_accuracy": .60,
            "strong_pick_accuracy": .63,
            "strong_pick_desired_coverage": .25,
        },
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "version": VERSION,
        "selected": selected,
        "probability_engine": probability_engine,
        "holdout_v11_2": m112,
        "holdout_residual_directional": mdir,
        "research_strong_band": mstrong,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
