from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import point_in_time_v13 as pit
from . import extra_innings_v13
from . import v13_distribution_prior
from .pipeline_v13 import ProbabilityPipelineV13
from .probability_contract_v13 import attach_contract, assert_no_market_leakage

VERSION = "13.1-professional-probability-v1"
_INSTALLED = False

V13_OPTION_FIELDS = (
    "p_baseball_raw", "p_baseball_calibrated", "p_posterior", "model_market_gap",
    "baseball_probability_source", "calibration_source_v13", "calibration_n_v13",
    "probability_interval_low", "probability_interval_high", "probability_uncertainty_v13",
    "p_legacy_market_blended", "probability_product", "edge_probability_field",
    "posterior_allowed_for_edge", "v13_probability_error", "v13_probability_eligible",
)


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _as_pipeline(value: ProbabilityPipelineV13 | dict[str,Any] | None) -> ProbabilityPipelineV13:
    if isinstance(value, ProbabilityPipelineV13):
        return value
    if isinstance(value, dict):
        return ProbabilityPipelineV13(value)
    return ProbabilityPipelineV13.from_artifact()


def _option_key(opt: dict[str,Any]) -> tuple[str,str,str]:
    return (str(opt.get("market") or ""), str(opt.get("name") or ""), str(opt.get("point")))


def upgrade_option(opt: dict[str,Any], phase: str, pipeline: ProbabilityPipelineV13 | dict[str,Any] | None = None) -> dict[str,Any]:
    pipeline = _as_pipeline(pipeline)
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


def upgrade_result(result: dict[str,Any], pipeline: ProbabilityPipelineV13 | dict[str,Any] | None = None) -> dict[str,Any]:
    pipeline = _as_pipeline(pipeline)
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
    original_bootstrap_prior = engine_v12._bootstrap_prior

    def neutral_extra_innings_home_win(home_mu, away_mu, dispersion=None, env_sigma=None):
        joint = original_joint(home_mu, away_mu, dispersion=dispersion, env_sigma=env_sigma)
        return extra_innings_v13.home_win_probability(joint, extra_innings_home_prior=None)

    # Remove the fixed 52% home split in extra innings until a separately
    # validated extra-inning prior exists.
    engine_v12.prob_home_win = neutral_extra_innings_home_win

    def validated_distribution_prior(structural_hmu, structural_amu, champ, phase):
        values = list(original_bootstrap_prior(structural_hmu, structural_amu, champ, phase))
        # Tuple contract from engine_v12._bootstrap_prior:
        # hmu, amu, run_meta, bootstrap, dispersion, dispersion_source,
        # env_sigma, env_source.
        dispersion, env_sigma, meta = v13_distribution_prior.apply(values[4], values[6], phase)
        if meta.get("active"):
            values[4] = dispersion
            values[5] = meta.get("source")
            # The ablation selected dispersion-only. Keep the already validated
            # environment sigma unchanged (currently 0.08) by contract.
            values[6] = env_sigma
            bootstrap = dict(values[3] or {})
            bootstrap["v13_distribution_prior"] = meta
            values[3] = bootstrap
        return tuple(values)

    # Activate the historical distribution prior only at the exact point where
    # score-distribution parameters are selected. Probability calibration and
    # sharp-market benchmarking remain completely separate.
    engine_v12._bootstrap_prior = validated_distribution_prior

    def analyze(game, event, as_of=None):
        result = original_analyze(game, event, as_of=as_of)
        return upgrade_result(result)

    def row(result, run_id, at, snapshot=None, source_replay=None):
        payload = original_row(result, run_id, at, snapshot, source_replay)
        live = {_option_key(o): o for o in result.get("options") or []}
        for saved in payload.get("options") or []:
            src = live.get(_option_key(saved)) or {}
            for field in V13_OPTION_FIELDS:
                saved[field] = src.get(field)
        attach_contract(payload)
        as_of = str(payload.get("analyzed_at") or at or datetime.now(timezone.utc).isoformat())
        # Production rows are backed by the run's current/replayed pregame HTTP
        # sources; historical reconstruction has its own stricter migration gate.
        pit.mark_live_snapshot(payload, as_of)
        payload["software_version"] = VERSION
        payload["probability_contract_version"] = VERSION
        payload["probability_product"] = "baseball-only-calibrated"
        payload["predictive_compatibility_independent_of_software_version"] = True
        return payload

    engine_v12.analyze = analyze
    runner.engine.analyze = analyze
    runner._row = row
    config.VERSION = VERSION
    _INSTALLED = True
    return True
