#!/usr/bin/env python3
"""V10 step-1 integration runner.

Keeps the stable V9.1.1 core untouched while replacing its deterministic run
baseline at runtime on the dedicated v10-professional branch. This is a
validation bridge only; once the V10 blocks are validated they will be folded
back into a single bot.py.
"""
import os
import sys
from pathlib import Path

import bot as core
from v10_step1_engine import advanced_base_runs, expected_starter_ip, self_test as engine_self_test

V10_FEATURE_VERSION = "10.0.0"
V10_MODEL_VERSION = "runs-residual-walkforward-v4"
V10_VERDICT_VERSION = "direction-calibrated-v4"
V10_RECOMMENDATION_VERSION = "model-first-v2"

# V10 writes to its own history. Old V9 snapshots must never train a model whose
# deterministic target changed underneath them.
core.VERSION = "10.0.0-step1"
core.FEATURE_VERSION = V10_FEATURE_VERSION
core.MODEL_VERSION = V10_MODEL_VERSION
core.VERDICT_VERSION = V10_VERDICT_VERSION
core.RECOMMENDATION_VERSION = V10_RECOMMENDATION_VERSION
core.HISTORY_FILE = Path(os.getenv("V10_HISTORY_FILE", "data/mlb_history_v10.jsonl"))
core.ARCHIVE_DIR = core.HISTORY_FILE.parent / "archive_v10"
core.STATE_FILE = core.HISTORY_FILE.parent / "v10_state.json"

_original_game_context = core.game_context


def _starter_for_engine(raw):
    """Use V9 shrinkage but add starts so expected innings are workload-aware."""
    out = core.shrunk_pitcher(raw)
    out = dict(out)
    out["gs"] = max(0.0, core.num((raw or {}).get("gamesStarted"), 0))
    return out


def game_context_v10(game):
    """Build the proven V9 context, then replace only the deterministic run base."""
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
        home_h,
        away_p,
        ctx["home_recent"],
        away_sp,
        ctx["away_bp"],
        ctx["home_lineup"],
        ctx["home_split"],
        ctx["home_statcast"],
        ctx["park"],
        ctx["weather"],
        True,
        lg,
    )
    away_mu = advanced_base_runs(
        away_h,
        home_p,
        ctx["away_recent"],
        home_sp,
        ctx["home_bp"],
        ctx["away_lineup"],
        ctx["away_split"],
        ctx["away_statcast"],
        ctx["park"],
        ctx["weather"],
        False,
        lg,
    )

    ctx["base_home_v9"] = ctx["base_home"]
    ctx["base_away_v9"] = ctx["base_away"]
    ctx["base_home"] = home_mu
    ctx["base_away"] = away_mu
    ctx["base_engine"] = "advanced-baseball-v10"
    ctx["expected_away_sp_ip"] = expected_starter_ip(away_sp)
    ctx["expected_home_sp_ip"] = expected_starter_ip(home_sp)
    return ctx


core.game_context = game_context_v10


def latest_pregame_snapshot_v10(record, feature=None):
    """Dynamic V10 version filter; avoids the V9 default-argument version capture."""
    feature = feature or core.FEATURE_VERSION
    snaps = [
        x
        for x in record.get("snapshots", [])
        if core.num(x.get("seconds_to_game"), -1) >= 0
        and x.get("feature_version") == feature
        and x.get("model_version") == core.MODEL_VERSION
        and x.get("distribution_version") == core.DIST_VERSION
    ]
    return max(snaps, key=lambda x: x.get("analyzed_at", "")) if snaps else None


core.latest_pregame_snapshot = latest_pregame_snapshot_v10


def self_test():
    engine_self_test()
    core.self_test()

    # Version/history isolation is part of the statistical correctness of V10.
    assert core.FEATURE_VERSION == V10_FEATURE_VERSION
    assert core.MODEL_VERSION == V10_MODEL_VERSION
    assert "v10" in str(core.HISTORY_FILE)

    # Workload weighting sanity check.
    short = {"gs": 20, "ip": 80, "era": 4.35, "whip": 1.32, "k9": 8.3, "bb9": 3.2}
    long = {"gs": 20, "ip": 130, "era": 4.35, "whip": 1.32, "k9": 8.3, "bb9": 3.2}
    assert expected_starter_ip(long) > expected_starter_ip(short)
    print("SELF-TEST V10 STEP1 INTEGRATION OK")


def main():
    core.logging.info("V10 step1 actif | moteur de base=%s | feature=%s", "advanced-baseball-v10", core.FEATURE_VERSION)
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
