from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import point_in_time_v13 as pit
from . import extra_innings_v13
from .pipeline_v13 import ProbabilityPipelineV13
from .probability_contract_v13 import attach_contract, assert_no_market_leakage

VERSION = "13.0-professional-probability-v1"
_INSTALLED = False


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def upgrade_option(opt: dict[str,Any], phase: str, pipeline: ProbabilityPipelineV13) -> dict[str,Any]:
    legacy_effective = opt.get("p_effective")
    pipeline.transform_option(opt, phase)
    opt["p_legacy_market_blended"] = legacy_effective

    # Downstream legacy selector/report code reads p_effective/p_win. In V13
    # those aliases intentionally point to calibrated baseball-only probability.
    calibrated = float(opt["p_baseball_calibrated"])
    raw = float(opt["p_baseball_raw"])
    push = max(0.0, min(.35, _num(opt.get("p_push_model", opt.get("p_push")), 0.0)))
    opt["p_effective"] = round(calibrated, 6)
    opt["p_model"] = round(raw, 6)
    opt["p_win"] = round(calibrated*(1-push), 6)
    opt["p_push"] = round(push, 6)
    opt["probability_product"] = "calibrated-baseball-only"
    opt["edge_probability_field"] = "p_baseball_calibrated"
    opt["posterior_allowed_for_edge"] = False
    assert_no_market_leakage(opt)
    return opt


def upgrade_result(result: dict[str,Any], pipeline: ProbabilityPipelineV13 | None = None) -> dict[str,Any]:
    pipeline = ProbabilityPipelineV13.from_artifact() if pipeline is None else pipeline
    phase = str(result.get("phase") or "EARLY").upper()
    for opt in result.get("options") or []:
        try:
            upgrade_option(opt, phase, pipeline)
        except Exception as exc:
            opt["v13_probability_error"] = f"{type(exc).__name__}:{exc}"
            opt["v13_probability_eligible"] = False
    home = str((result.get("ctx") or {}).get("home") or "")
    hm = next((o for o in result.get("options") or []
               if str(o.get("market") or "").upper() == "ML" and str(o.get("name") or "") == home), None)
    if hm and hm.get("p_baseball_calibrated") is not None:
        result["p_home"] = hm["p_baseball_calibrated"]
    result["probability_contract_version"] = VERSION
    result["probability_product"] = "baseball-only-calibrated"
    result["market_blend_allowed_for_edge"] = False
    result["market_blend_allowed_for_forecast_only"] = True
    result["probability_pipeline"] = "PregameSnapshot->BaseballModel->ScoreDistribution->BaseballCalibration->MarketBenchmark"
    return result


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import config, engine_v12, runner

    original_analyze = engine_v12.analyze
    original_row = runner._row
    original_joint = engine_v12.joint_score_matrix

    def neutral_extra_innings_home_win(home_mu, away_mu, dispersion=None, env_sigma=None):
        joint = original_joint(home_mu, away_mu, dispersion=dispersion, env_sigma=env_sigma)
        return extra_innings_v13.home_win_probability(joint, extra_innings_home_prior=None)

    # Remove the fixed 52% home split in extra innings until a separately
    # validated extra-inning prior exists.
    engine_v12.prob_home_win = neutral_extra_innings_home_win

    def analyze(game, event, as_of=None):
        result = original_analyze(game, event, as_of=as_of)
        return upgrade_result(result)

    def row(result, run_id, at, snapshot=None, source_replay=None):
        payload = original_row(result, run_id, at, snapshot, source_replay)
        attach_contract(payload)
        as_of = str(payload.get("analyzed_at") or at or datetime.now(timezone.utc).isoformat())
        # Production rows are backed by the run's current/replayed pregame HTTP
        # sources; historical reconstruction has its own stricter migration gate.
        pit.mark_live_snapshot(payload, as_of)
        payload["software_version"] = VERSION
        payload["predictive_compatibility_independent_of_software_version"] = True
        return payload

    engine_v12.analyze = analyze
    runner.engine.analyze = analyze
    runner._row = row
    config.VERSION = VERSION
    _INSTALLED = True
    return True
