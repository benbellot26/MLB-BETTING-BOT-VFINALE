from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path("data/v124_historical_warmstart.json")


def _gain(block, metric):
    base = (block.get("baseline") or {}).get(metric)
    opt = (block.get("optimized") or {}).get(metric)
    if base is None or opt is None:
        return None
    return float(base) - float(opt)


def harden(model):
    wf = model.get("walk_forward") or {}
    frozen = model.get("frozen_test") or {}
    wf_gains = {
        "brier": _gain(wf, "brier"),
        "logloss": _gain(wf, "logloss"),
        "team_run_mae": _gain(wf, "team_run_mae"),
        "total_run_mae": _gain(wf, "total_run_mae"),
    }
    frozen_gains = {
        "brier": frozen.get("brier_improvement"),
        "logloss": frozen.get("logloss_improvement"),
        "team_run_mae": frozen.get("team_run_mae_improvement"),
    }
    checks = {
        "minimum_games": int(model.get("historical_reconstructed_games") or 0) >= int(model.get("minimum_games") or 600),
        "walk_forward_active": wf.get("status") == "ACTIVE" and int(wf.get("windows") or 0) >= 3,
        "walk_forward_brier_non_regression": wf_gains["brier"] is not None and wf_gains["brier"] >= 0.0,
        "walk_forward_logloss_non_regression": wf_gains["logloss"] is not None and wf_gains["logloss"] >= 0.0,
        "walk_forward_team_run_tolerance": wf_gains["team_run_mae"] is not None and wf_gains["team_run_mae"] >= -0.02,
        "frozen_brier_non_regression": frozen_gains["brier"] is not None and frozen_gains["brier"] >= 0.0,
        "frozen_logloss_non_regression": frozen_gains["logloss"] is not None and frozen_gains["logloss"] >= 0.0,
        "frozen_team_run_tolerance": frozen_gains["team_run_mae"] is not None and frozen_gains["team_run_mae"] >= -0.02,
        "frozen_not_fit": frozen.get("used_for_weight_fitting") is False,
        "no_historical_odds": (model.get("guardrails") or {}).get("historical_odds_used") is False,
        "no_roi_training": (model.get("guardrails") or {}).get("roi_used_for_training") is False,
        "production_isolated": (model.get("guardrails") or {}).get("affects_v12_selection") is False,
    }
    eligible = all(checks.values())
    model["eligible_for_warm_start"] = eligible
    model["status"] = "ELIGIBLE" if eligible else "DIAGNOSTIC_ONLY"
    model["out_of_sample_gate"] = {
        "passes": eligible,
        "checks": checks,
        "walk_forward_gains": wf_gains,
        "frozen_test_gains": frozen_gains,
        "policy": "Historical weights may warm-start V12.4 optimized shadow only when aggregate chronological walk-forward and untouched frozen test both avoid probability-score regression.",
    }
    return model


def harden_file(path=DEFAULT_PATH):
    path = Path(path)
    model = json.loads(path.read_text(encoding="utf-8"))
    model = harden(model)
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return model


if __name__ == "__main__":
    print(json.dumps(harden_file(), ensure_ascii=False, indent=2, sort_keys=True))
