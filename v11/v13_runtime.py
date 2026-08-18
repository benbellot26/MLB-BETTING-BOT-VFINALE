from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import point_in_time_v13 as pit
from . import extra_innings_v13
from . import v13_distribution_prior
from . import v13_run_mean_runtime
from . import v13_rich_run_shadow
from .pipeline_v13 import ProbabilityPipelineV13
from .probability_contract_v13 import (
    attach_contract,
    assert_no_market_leakage,
    PREDICTIVE_CONTRACT_VERSION,
    MODEL_GENERATION_FINGERPRINT,
)

VERSION = "13.5.2-professional-probability-v1"
_INSTALLED = False

V13_OPTION_FIELDS = (
    "p_baseball_raw", "p_baseball_calibrated", "p_posterior", "p_predictive_final", "model_market_gap",
    "baseball_probability_source", "calibration_source_v13", "calibration_n_v13",
    "calibration_phase_n_v13", "calibration_market_n_v13", "reliability_source_v13",
    "probability_interval_low", "probability_interval_high", "probability_uncertainty_v13",
    "predictive_final_source", "predictive_final_status",
    "p_legacy_market_blended", "probability_product", "edge_probability_field",
    "posterior_allowed_for_edge", "selector_uncertainty_source",
    "v13_probability_error", "v13_probability_eligible",
)


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _as_pipeline(value: ProbabilityPipelineV13 | dict[str,Any] | None) -> ProbabilityPipelineV13:
    if isinstance(value, ProbabilityPipelineV13): return value
    if isinstance(value, dict): return ProbabilityPipelineV13(value)
    return ProbabilityPipelineV13.from_artifact()


def _option_key(opt: dict[str,Any]) -> tuple[str,str,str]:
    return (str(opt.get("market") or ""), str(opt.get("name") or ""), str(opt.get("point")))


def upgrade_option(opt: dict[str,Any], phase: str, pipeline: ProbabilityPipelineV13 | dict[str,Any] | None = None,
                   data_quality: float = 1.0) -> dict[str,Any]:
    pipeline = _as_pipeline(pipeline)
    legacy_effective = opt.get("p_effective")
    pipeline.transform_option(opt, phase, data_quality=data_quality)
    opt["p_legacy_market_blended"] = legacy_effective
    calibrated = float(opt["p_baseball_calibrated"]); raw = float(opt["p_baseball_raw"])
    push = max(0.0, min(.35, _num(opt.get("p_push_model", opt.get("p_push")), 0.0)))
    opt["p_effective"] = round(calibrated, 6); opt["p_model"] = round(raw, 6)
    opt["p_win"] = round(calibrated*(1-push), 6); opt["p_push"] = round(push, 6)

    # Predictive-analytics product contract:
    # - baseball calibrated remains the primary probability until a market-aware
    #   ensemble has demonstrated an out-of-sample Brier + LogLoss improvement;
    # - p_posterior stays available as a shadow candidate and is scored separately.
    # This prevents a tiny recent sample from silently changing the user-facing
    # probability while still collecting the evidence needed to promote it later.
    opt["p_predictive_final"] = round(calibrated, 6)
    opt["predictive_final_source"] = "baseball_calibrated"
    opt["predictive_final_status"] = "BASEBALL_PRIMARY_POSTERIOR_SHADOW"

    opt["probability_product"] = "calibrated-baseball-only"
    opt["edge_probability_field"] = "p_baseball_calibrated"; opt["posterior_allowed_for_edge"] = False
    assert_no_market_leakage(opt)
    return opt


def upgrade_result(result: dict[str,Any], pipeline: ProbabilityPipelineV13 | dict[str,Any] | None = None) -> dict[str,Any]:
    pipeline = _as_pipeline(pipeline); phase = str(result.get("phase") or "EARLY").upper()
    from . import data_quality
    dq = result.get("data_quality") if isinstance(result.get("data_quality"), dict) else data_quality.assess(result)
    result["data_quality"] = dq
    dq_score = max(0.0, min(1.0, _num(dq.get("model_input_score", dq.get("score")), 1.0)))
    for opt in result.get("options") or []:
        try: upgrade_option(opt, phase, pipeline, data_quality=dq_score)
        except Exception as exc:
            opt["v13_probability_error"] = f"{type(exc).__name__}:{exc}"; opt["v13_probability_eligible"] = False
    home = str((result.get("ctx") or {}).get("home") or "")
    hm = next((o for o in result.get("options") or [] if str(o.get("market") or "").upper()=="ML" and str(o.get("name") or "")==home), None)
    if hm and hm.get("p_baseball_calibrated") is not None: result["p_home"] = hm["p_baseball_calibrated"]
    result["software_version"] = VERSION
    result["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION
    result["model_generation"] = MODEL_GENERATION_FINGERPRINT
    result["probability_product"] = "baseball-only-calibrated"
    result["predictive_analytics_mode"] = True
    result["primary_probability_field"] = "p_predictive_final"
    result["posterior_role"] = "shadow_candidate_until_out_of_sample_validation"
    result["market_blend_allowed_for_edge"] = False; result["market_blend_allowed_for_forecast_only"] = True
    result["probability_pipeline"] = "PregameSnapshot->BaseballModel->RunMeanPrior->ScoreDistribution->BaseballCalibration->MarketBenchmark"
    return result


def install() -> bool:
    global _INSTALLED
    if _INSTALLED: return True
    from . import config, engine_v12, runner, methodology_v123
    original_analyze = engine_v12.analyze; original_row = runner._row
    original_joint = engine_v12.joint_score_matrix
    # V12.3's active project path calls methodology_v123.bootstrap_prior_v123
    # directly through compose_runtime().  Hook that exact function, not only
    # engine_v12._bootstrap_prior, otherwise V13 baseline/transfer logic is bypassed.
    original_bootstrap_prior = methodology_v123.bootstrap_prior_v123
    original_analysis_points = engine_v12._analysis_points

    def neutral_extra_innings_home_win(home_mu, away_mu, dispersion=None, env_sigma=None):
        joint = original_joint(home_mu, away_mu, dispersion=dispersion, env_sigma=env_sigma)
        return extra_innings_v13.home_win_probability(joint, extra_innings_home_prior=None)
    engine_v12.prob_home_win = neutral_extra_innings_home_win

    def v13_analysis_points(event, key, home=None, as_of=None):
        """Keep the standard +/-1.5 RL surface visible for both teams.

        The core engine creates complementary pairs from each home-team point.  By
        ensuring both -1.5 and +1.5 are present, every game exposes home -1.5,
        away +1.5, home +1.5 and away -1.5.  Missing execution prices remain
        missing and therefore cannot bypass the selector's execution/value gates.
        """
        points, source = original_analysis_points(event, key, home, as_of)
        if key != "spreads":
            return points, source
        merged = {round(_num(p), 2) for p in (points or [])}
        before = set(merged)
        merged.update({-1.5, 1.5})
        if merged != before:
            source = f"{source}+v13-standard-1.5" if source and source != "none" else "v13-standard-1.5"
        return sorted(merged), source
    engine_v12._analysis_points = v13_analysis_points

    def validated_historical_priors(structural_hmu, structural_amu, champ, phase):
        values = list(original_bootstrap_prior(structural_hmu, structural_amu, champ, phase))
        phase_name = str(phase or "EARLY").upper(); phase_model = ((champ.get("phase_models") or {}).get(phase_name) or {})
        native_residual_active = bool(champ.get("active") and (phase_model.get("residual") or {}).get("active"))

        # Freeze the baseline before either V13 historical layer is applied.
        # These values are persisted in replay evidence so transfer tests always
        # compare baseline -> candidate, never candidate -> candidate squared.
        validation_meta = dict(values[2] or {})
        validation_meta.update({
            "v13_validation_baseline_home_mu": values[0],
            "v13_validation_baseline_away_mu": values[1],
            "v13_validation_baseline_dispersion": values[4],
            "v13_validation_baseline_environment_sigma": values[6],
            "v13_validation_model_generation": MODEL_GENERATION_FINGERPRINT,
            "v13_validation_baseline_source": "v123-compose-runtime-pre-v13-candidate",
        })
        values[2] = validation_meta
        legacy_run_prior_active = bool(validation_meta.get("active"))

        if phase_name == "FINAL" and not native_residual_active and not legacy_run_prior_active:
            hmu, amu, mean_meta = v13_run_mean_runtime.apply_pair(values[0], values[1], phase_name)
            if mean_meta.get("active"):
                values[0], values[1] = hmu, amu; bootstrap = dict(values[3] or {})
                bootstrap["v13_run_mean_prior"] = mean_meta; values[3] = bootstrap
        dispersion, env_sigma, dist_meta = v13_distribution_prior.apply(values[4], values[6], phase_name)
        if dist_meta.get("active"):
            values[4] = dispersion; values[5] = dist_meta.get("source"); values[6] = env_sigma
            bootstrap = dict(values[3] or {}); bootstrap["v13_distribution_prior"] = dist_meta; values[3] = bootstrap
        return tuple(values)

    # Keep both aliases in sync.  project_v123() resolves the methodology module
    # global at call time, while some legacy paths still call engine_v12 directly.
    methodology_v123.bootstrap_prior_v123 = validated_historical_priors
    engine_v12._bootstrap_prior = validated_historical_priors

    def analyze(game, event, as_of=None):
        result = original_analyze(game, event, as_of=as_of)
        run_prior_meta = ((((result.get("features") or {}).get("historical_bootstrap") or {}).get("run_prior")) or {})
        result["v13_validation_baseline"] = {
            "home_mu": run_prior_meta.get("v13_validation_baseline_home_mu"),
            "away_mu": run_prior_meta.get("v13_validation_baseline_away_mu"),
            "dispersion": run_prior_meta.get("v13_validation_baseline_dispersion"),
            "environment_sigma": run_prior_meta.get("v13_validation_baseline_environment_sigma"),
            "model_generation": run_prior_meta.get("v13_validation_model_generation"),
            "source": run_prior_meta.get("v13_validation_baseline_source"),
        }
        result["v13_validation_baseline_ready"] = (
            all(result["v13_validation_baseline"].get(k) is not None for k in ("home_mu","away_mu","dispersion","environment_sigma"))
            and result["v13_validation_baseline"].get("model_generation") == MODEL_GENERATION_FINGERPRINT
        )
        before = bool((result.get("shadow_v124") or {}).get("modules"))
        v13_rich_run_shadow.attach(result)
        result["v13_shadow_chain"] = {
            "v124_modules_before_rich": before,
            "rich_status": (result.get("shadow_v13_rich_runs") or {}).get("status"),
            "affects_probability": False,
        }
        return upgrade_result(result)

    def row(result, run_id, at, snapshot=None, source_replay=None):
        payload = original_row(result, run_id, at, snapshot, source_replay)
        live = {_option_key(o): o for o in result.get("options") or []}
        for saved in payload.get("options") or []:
            src = live.get(_option_key(saved)) or {}
            for field in V13_OPTION_FIELDS: saved[field] = src.get(field)
        payload["data_quality"] = result.get("data_quality")
        payload["shadow_v13_rich_runs"] = result.get("shadow_v13_rich_runs")
        payload["v13_shadow_chain"] = result.get("v13_shadow_chain")
        payload["v13_validation_baseline"] = result.get("v13_validation_baseline")
        payload["v13_validation_baseline_ready"] = result.get("v13_validation_baseline_ready")
        attach_contract(payload)
        as_of = str(payload.get("analyzed_at") or at or datetime.now(timezone.utc).isoformat())
        pit.mark_live_snapshot(payload, as_of)
        payload["software_version"] = VERSION
        payload["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION
        payload["model_generation"] = MODEL_GENERATION_FINGERPRINT
        payload["probability_product"] = "baseball-only-calibrated"; payload["predictive_compatibility_independent_of_software_version"] = True
        payload["predictive_analytics_mode"] = True
        payload["primary_probability_field"] = "p_predictive_final"
        return payload

    engine_v12.analyze = analyze; runner.engine.analyze = analyze; runner._row = row; config.VERSION = VERSION
    _INSTALLED = True; return True
