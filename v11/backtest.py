from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from . import config, pro_model, storage
from .journal import load_rows


def _num(x, d=0.0):
    try: return float(x)
    except Exception: return d


def _triplet(cond, push):
    cond = max(.001, min(.999, _num(cond, .5))); push = max(0.0, min(.95, _num(push, 0)))
    return {"win": cond*(1-push), "push": push, "loss": (1-cond)*(1-push)}


def _score_triplets(preds, actuals):
    if not preds: return {"n": 0}
    brier = []; logloss = []
    for p, actual in zip(preds, actuals):
        y = {"win": 0.0, "push": 0.0, "loss": 0.0}; y[actual] = 1.0
        brier.append(sum((p[k]-y[k])**2 for k in y)); logloss.append(-math.log(max(.001, p[actual])))
    return {"n": len(preds), "multiclass_brier": sum(brier)/len(brier), "multiclass_logloss": sum(logloss)/len(logloss)}


def _market(rows, market):
    model, precal, sharp, actuals = [], [], [], []
    for r in rows:
        a, _ = pro_model.canonical_market_pair(r, market)
        if not a or a.get("result") not in {"WIN", "LOSS", "PUSH"}: continue
        actual = str(a.get("result")).lower(); actuals.append(actual)
        model.append({"win": max(0.0, _num(a.get("p_win"))), "push": max(0.0, _num(a.get("p_push"))),
                      "loss": max(0.0, 1-_num(a.get("p_win"))-_num(a.get("p_push")))})
        precal.append(_triplet(a.get("p_model"), a.get("p_push_model", a.get("p_push"))))
        sharp.append(_triplet(a.get("p_market") if a.get("p_market") is not None else .5, a.get("p_push_model", a.get("p_push"))))
    return {"n": len(actuals), "model": _score_triplets(model, actuals), "precalibration": _score_triplets(precal, actuals),
            "sharp_with_model_push": _score_triplets(sharp, actuals),
            "selection": "fixed canonical execution line; pushes retained as third outcome"}


def build_report(rows=None):
    rows = load_rows() if rows is None else rows
    compatible = pro_model.canonical_phase_rows(rows, compatible_only=True)
    phases = {}
    for phase in pro_model.PHASES:
        xs = pro_model.canonical_settled_rows(compatible, phase)
        phases[phase] = {"games": len(xs), "markets": {m: _market(xs, m) for m in ("ML", "RUNLINE", "TOTAL")}}
    all_rows = pro_model.canonical_settled_rows(compatible)
    candidate = pro_model.build_candidate(rows)
    finance = storage.ledger_summary(); evidence = pro_model.production_evidence_gate(finance)
    cohorts = Counter((str(r.get("engine_version")), str(r.get("feature_schema"))) for r in rows if r.get("result_status") == "FINAL")
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "engine": config.VERSION,
            "methodology": {"strict_v12_2_cohort": True, "point_in_time_only": True,
                            "phase_specific_models": True, "grouped_by_game": True,
                            "fixed_canonical_market_line": True, "pushes_scored_multinomial": True,
                            "end_to_end_stack_gate": True, "walk_forward_required_for_promotion": True,
                            "historical_odds_fabricated": False,
                            "claim_limit": "Only V12.2 rows with matching feature schema train/calibrate the challenger."},
            "compatible_games": len(all_rows), "phases": phases,
            "candidate": {"version": candidate.get("version"), "training_games": (candidate.get("metadata") or {}).get("training_games_available"),
                          "stack_validation": candidate.get("stack_validation"), "walk_forward_gate": candidate.get("walk_forward_gate"),
                          "promotion_gate": candidate.get("promotion_gate"), "passes": candidate.get("passes")},
            "production_evidence": evidence, "betting": finance,
            "settled_cohorts": [{"engine_version": k[0], "feature_schema": k[1], "rows": n} for k, n in cohorts.items()]}


def write_report(path="data/v11_point_in_time_backtest.json"):
    rep = build_report(); p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"); return rep


if __name__ == "__main__": print(json.dumps(write_report(), ensure_ascii=False, indent=2, sort_keys=True))
