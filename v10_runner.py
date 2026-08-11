#!/usr/bin/env python3
"""V10 step-2 integration runner.

Validation bridge for:
1) advanced deterministic baseball run engine;
2) phase-isolated EARLY/LATE/FINAL residual learning and calibration.

main remains on stable V9.1.1. No workflow is modified here.
"""
import os
import sys
from pathlib import Path

import bot as core
from v10_step1_engine import advanced_base_runs, expected_starter_ip, self_test as engine_self_test

V10_FEATURE_VERSION = "10.1.0"
V10_MODEL_VERSION = "runs-residual-phase-walkforward-v5"
V10_VERDICT_VERSION = "direction-calibrated-v4"
V10_RECOMMENDATION_VERSION = "model-first-v2"

# V10 uses an isolated history because both the deterministic target and the
# training semantics differ from V9.
core.VERSION = "10.0.0-step2"
core.FEATURE_VERSION = V10_FEATURE_VERSION
core.MODEL_VERSION = V10_MODEL_VERSION
core.VERDICT_VERSION = V10_VERDICT_VERSION
core.RECOMMENDATION_VERSION = V10_RECOMMENDATION_VERSION
core.HISTORY_FILE = Path(os.getenv("V10_HISTORY_FILE", "data/mlb_history_v10.jsonl"))
core.ARCHIVE_DIR = core.HISTORY_FILE.parent / "archive_v10"
core.STATE_FILE = core.HISTORY_FILE.parent / "v10_state.json"

# Import only after V10 version constants are installed on the shared core.
from v10_phase_models import (
    PHASES,
    build_cal_states,
    build_run_states,
    build_skill_states,
    select_phase_states,
    self_test as phase_self_test,
)

_original_game_context = core.game_context
_original_analyze_base = core.analyze_base
_PHASE_RUN_PARENT = None


def _starter_for_engine(raw):
    """Use the existing shrinkage and add starts for workload-aware innings."""
    out = dict(core.shrunk_pitcher(raw))
    out["gs"] = max(0.0, core.num((raw or {}).get("gamesStarted"), 0))
    return out


def game_context_v10(game):
    """Build the stable context, then replace only the deterministic run base."""
    ctx = _original_game_context(game)

    home_h = core.season_stats(ctx["home_id"], "hitting")
    home_p = core.season_stats(ctx["home_id"], "pitching")
    away_h = core.season_stats(ctx["away_id"], "hitting")
    away_p = core.season_stats(ctx["away_id"], "pitching")

    home_sp = _starter_for_engine(ctx.get("home_sp_stats") or {})
    away_sp = _starter_for_engine(ctx.get("away_sp_stats") or {})
    lg = core.league_baselines()

    # Home hitters face away starter/bullpen; away hitters face home starter/bullpen.
    home_mu = advanced_base_runs(
        home_h, away_p, ctx["home_recent"], away_sp, ctx["away_bp"],
        ctx["home_lineup"], ctx["home_split"], ctx["home_statcast"],
        ctx["park"], ctx["weather"], True, lg,
    )
    away_mu = advanced_base_runs(
        away_h, home_p, ctx["away_recent"], home_sp, ctx["home_bp"],
        ctx["away_lineup"], ctx["away_split"], ctx["away_statcast"],
        ctx["park"], ctx["weather"], False, lg,
    )

    old_home = ctx["base_home"]
    old_away = ctx["base_away"]
    ctx["base_home_v9"] = old_home
    ctx["base_away_v9"] = old_away
    ctx["base_home"] = home_mu
    ctx["base_away"] = away_mu
    ctx["base_engine"] = "advanced-baseball-v10"
    ctx["expected_away_sp_ip"] = expected_starter_ip(away_sp)
    ctx["expected_home_sp_ip"] = expected_starter_ip(home_sp)

    core.logging.info(
        "V10 RUN BASE | %s @ %s | H %.2f→%.2f (%+.2f) | A %.2f→%.2f (%+.2f) | SP IP H/A %.2f/%.2f",
        ctx["away"], ctx["home"],
        old_home, home_mu, home_mu - old_home,
        old_away, away_mu, away_mu - old_away,
        ctx["expected_home_sp_ip"], ctx["expected_away_sp_ip"],
    )
    return ctx


core.game_context = game_context_v10


def latest_pregame_snapshot_v10(record, feature=None):
    """Dynamic V10 version filter; avoids V9 default-argument version capture."""
    feature = feature or core.FEATURE_VERSION
    snaps = [
        x for x in record.get("snapshots", [])
        if core.num(x.get("seconds_to_game"), -1) >= 0
        and x.get("feature_version") == feature
        and x.get("model_version") == core.MODEL_VERSION
        and x.get("distribution_version") == core.DIST_VERSION
    ]
    return max(snaps, key=lambda x: x.get("analyzed_at", "")) if snaps else None


core.latest_pregame_snapshot = latest_pregame_snapshot_v10


def run_model_state_v10(hist):
    """Build three independent residual models, one per information phase."""
    global _PHASE_RUN_PARENT
    _PHASE_RUN_PARENT = build_run_states(hist)
    for phase in PHASES:
        s = _PHASE_RUN_PARENT["phase_states"][phase]
        core.logging.info(
            "V10 PHASE RUN | %s n=%d active=%s RMSE=%s/%s gainProb=%.2f folds=%d",
            phase, s["n"], s["active"],
            f"{s['rmse_model']:.3f}" if s["rmse_model"] is not None else "-",
            f"{s['rmse_base']:.3f}" if s["rmse_base"] is not None else "-",
            s["gain_prob"], s["folds"],
        )
    return _PHASE_RUN_PARENT


def calibration_state_v10(hist, _engine_mode):
    """Calibrate EARLY/LATE/FINAL independently using the matching run engine."""
    global _PHASE_RUN_PARENT
    if _PHASE_RUN_PARENT is None:
        _PHASE_RUN_PARENT = build_run_states(hist)
    parent = build_cal_states(hist, _PHASE_RUN_PARENT)
    for phase in PHASES:
        s = parent["phase_states"][phase]
        core.logging.info(
            "V10 PHASE CAL | %s n=%d active=%s Brier=%s→%s gainProb=%.2f",
            phase, s["n"], s["active"],
            f"{s['brier_raw']:.4f}" if s["brier_raw"] is not None else "-",
            f"{s['brier_cal']:.4f}" if s["brier_cal"] is not None else "-",
            s["gain_prob"],
        )
    return parent


def skill_state_v10(hist, _engine_mode):
    """Keep model-vs-market skill weights phase-specific as well."""
    global _PHASE_RUN_PARENT
    if _PHASE_RUN_PARENT is None:
        _PHASE_RUN_PARENT = build_run_states(hist)
    parent = build_skill_states(hist, _PHASE_RUN_PARENT)
    for phase in PHASES:
        s = parent["phase_states"][phase]
        core.logging.info(
            "V10 PHASE SKILL | %s n=%d model_weight=%.2f",
            phase, s["n"], s["model_weight"],
        )
    return parent


core.run_model_state = run_model_state_v10
core.calibration_state = calibration_state_v10
core.skill_state = skill_state_v10


def analyze_base_v10(game, event, delta, states, hist):
    """Select only the state trained for the current prediction phase."""
    seconds = (core.parse_dt(game["gameDate"]) - core.NOW).total_seconds()
    phase = core.snapshot_phase(seconds)
    phase_states = select_phase_states(states, phase)
    result = _original_analyze_base(game, event, delta, phase_states, hist)
    run_state, _, cal_state, skill = phase_states
    result["phase_model_n"] = run_state.get("n", 0)
    result["phase_cal_n"] = cal_state.get("n", 0)
    result["phase_skill_n"] = skill.get("n", 0)
    core.logging.info(
        "V10 PHASE SELECT | %s @ %s | phase=%s run_n=%d run_active=%s cal_n=%d cal_active=%s skill_n=%d",
        result["ctx"]["away"], result["ctx"]["home"], phase,
        result["phase_model_n"], run_state.get("active", False),
        result["phase_cal_n"], cal_state.get("active", False),
        result["phase_skill_n"],
    )
    return result


core.analyze_base = analyze_base_v10


def self_test():
    engine_self_test()
    phase_self_test()
    core.self_test()

    assert core.FEATURE_VERSION == V10_FEATURE_VERSION
    assert core.MODEL_VERSION == V10_MODEL_VERSION
    assert "v10" in str(core.HISTORY_FILE)

    short = {"gs": 20, "ip": 80, "era": 4.35, "whip": 1.32, "k9": 8.3, "bb9": 3.2}
    long = {"gs": 20, "ip": 130, "era": 4.35, "whip": 1.32, "k9": 8.3, "bb9": 3.2}
    assert expected_starter_ip(long) > expected_starter_ip(short)

    fake_states = (
        {"phase_states": {
            "EARLY": {"active": False, "model": None, "n": 11},
            "LATE": {"active": False, "model": None, "n": 22},
            "FINAL": {"active": True, "model": object(), "n": 33},
        }},
        {"alpha_home": .12, "alpha_away": .12},
        {"phase_states": {
            "EARLY": {"active": False, "model": None, "n": 10},
            "LATE": {"active": False, "model": None, "n": 20},
            "FINAL": {"active": True, "model": (0, 1), "n": 30},
        }},
        {"phase_states": {
            "EARLY": {"n": 9, "model_weight": .40},
            "LATE": {"n": 19, "model_weight": .45},
            "FINAL": {"n": 29, "model_weight": .55},
        }},
    )
    assert select_phase_states(fake_states, "EARLY")[0]["n"] == 11
    assert select_phase_states(fake_states, "FINAL")[0]["n"] == 33
    print("SELF-TEST V10 STEP2 INTEGRATION OK")


def main():
    core.logging.info(
        "V10 step2 actif | base=%s | apprentissage=%s | feature=%s",
        "advanced-baseball-v10", "EARLY/LATE/FINAL isolés", core.FEATURE_VERSION,
    )
    core.main()


if __name__ == "__main__":
    try:
        if "--self-test" in sys.argv:
            self_test()
        else:
            main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        core.logging.exception("ERREUR FATALE V10")
        raise
