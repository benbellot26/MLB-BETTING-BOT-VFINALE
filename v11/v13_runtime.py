from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import point_in_time_v13 as pit
from .pipeline_v13 import ProbabilityPipelineV13
from .probability_contract_v13 import (
    MODEL_GENERATION_FINGERPRINT,
    PREDICTIVE_CONTRACT_VERSION,
    attach_contract,
    assert_no_market_leakage,
)
from .v13_engine import V13Engine, VERSION

_INSTALLED = False
_ENGINE: V13Engine | None = None

V13_OPTION_FIELDS = (
    "p_baseball_raw",
    "p_baseball_calibrated",
    "p_posterior",
    "p_predictive_final",
    "model_market_gap",
    "baseball_probability_source",
    "calibration_source_v13",
    "calibration_n_v13",
    "calibration_phase_n_v13",
    "calibration_market_n_v13",
    "reliability_source_v13",
    "probability_interval_low",
    "probability_interval_high",
    "probability_uncertainty_v13",
    "posterior_weight_v13",
    "posterior_weight_source_v13",
    "posterior_weight_games_v13",
    "posterior_weight_policy_v13",
    "legacy_sharp_weight_v13",
    "predictive_final_source",
    "predictive_final_status",
    "p_legacy_market_blended",
    "probability_product",
    "edge_probability_field",
    "posterior_allowed_for_edge",
    "selector_uncertainty_source",
    "v13_probability_error",
    "v13_probability_eligible",
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _as_pipeline(value: ProbabilityPipelineV13 | dict[str, Any] | None) -> ProbabilityPipelineV13:
    if isinstance(value, ProbabilityPipelineV13):
        return value
    if isinstance(value, dict):
        # Explicit calibration injection remains deterministic for tests/research.
        return ProbabilityPipelineV13(value, {})
    return ProbabilityPipelineV13.from_artifact()


def _option_key(option: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(option.get("market") or ""),
        str(option.get("name") or ""),
        str(option.get("point")),
    )


def upgrade_option(
    option: dict[str, Any],
    phase: str,
    pipeline: ProbabilityPipelineV13 | dict[str, Any] | None = None,
    data_quality: float = 1.0,
) -> dict[str, Any]:
    """Backward-compatible single-option V13 probability-contract adapter."""
    pipeline = _as_pipeline(pipeline)
    legacy_effective = option.get("p_effective")
    pipeline.transform_option(option, phase, data_quality=data_quality)
    option["p_legacy_market_blended"] = legacy_effective
    calibrated = float(option["p_baseball_calibrated"])
    raw = float(option["p_baseball_raw"])
    push = max(0.0, min(0.35, _num(option.get("p_push_model", option.get("p_push")), 0.0)))
    option["p_effective"] = round(calibrated, 6)
    option["p_model"] = round(raw, 6)
    option["p_win"] = round(calibrated * (1.0 - push), 6)
    option["p_push"] = round(push, 6)
    option["p_predictive_final"] = round(calibrated, 6)
    option["predictive_final_source"] = "baseball_calibrated"
    option["predictive_final_status"] = "BASEBALL_PRIMARY_POSTERIOR_SHADOW"
    option["probability_product"] = "calibrated-baseball-only"
    option["edge_probability_field"] = "p_baseball_calibrated"
    option["posterior_allowed_for_edge"] = False
    assert_no_market_leakage(option)
    return option


def upgrade_result(
    result: dict[str, Any],
    pipeline: ProbabilityPipelineV13 | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility adapter retained for replay/tests outside ``V13Engine``."""
    pipeline = _as_pipeline(pipeline)
    phase = str(result.get("phase") or "EARLY").upper()
    from . import data_quality as dq_module

    dq = result.get("data_quality") if isinstance(result.get("data_quality"), dict) else dq_module.assess(result)
    result["data_quality"] = dq
    dq_score = max(0.0, min(1.0, _num(dq.get("model_input_score", dq.get("score")), 1.0)))
    for option in result.get("options") or []:
        try:
            upgrade_option(option, phase, pipeline, data_quality=dq_score)
        except Exception as exc:
            option["v13_probability_error"] = f"{type(exc).__name__}:{exc}"
            option["v13_probability_eligible"] = False
    home = str((result.get("ctx") or {}).get("home") or "")
    hm = next(
        (
            option
            for option in result.get("options") or []
            if str(option.get("market") or "").upper() == "ML"
            and str(option.get("name") or "") == home
        ),
        None,
    )
    if hm and hm.get("p_baseball_calibrated") is not None:
        result["p_home"] = hm["p_baseball_calibrated"]
    result["software_version"] = VERSION
    result["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION
    result["model_generation"] = MODEL_GENERATION_FINGERPRINT
    result["probability_product"] = "baseball-only-calibrated"
    result["predictive_analytics_mode"] = True
    result["primary_probability_field"] = "p_predictive_final"
    result["posterior_role"] = "shadow_candidate_until_unique_game_out_of_sample_validation"
    result["market_blend_allowed_for_edge"] = False
    result["market_blend_allowed_for_forecast_only"] = True
    return result


def runtime_hook_status() -> dict[str, Any]:
    """Compatibility name; reports explicit composition rather than V13 hooks."""
    from . import engine_v12, methodology_v123, runner

    explicit_engine = isinstance(runner.engine, V13Engine)
    row_adapter = bool(getattr(runner._row, "_v13_runtime_adapter", False))
    global_markers = {
        "engine_analyze": bool(getattr(engine_v12.analyze, "_v13_runtime_hook", False)),
        "bootstrap": bool(getattr(methodology_v123.bootstrap_prior_v123, "_v13_runtime_hook", False)),
        "analysis_points": bool(getattr(engine_v12._analysis_points, "_v13_runtime_hook", False)),
        "extra_innings": bool(getattr(engine_v12.prob_home_win, "_v13_runtime_hook", False)),
    }
    no_v13_engine_global_monkeypatches = not any(global_markers.values())
    return {
        "installed": bool(_INSTALLED),
        "architecture": "explicit-v13-engine",
        # Legacy status keys are retained so existing health consumers do not
        # break; True now means the responsibility is owned by V13Engine.
        "engine_analyze": explicit_engine,
        "runner_row": row_adapter,
        "bootstrap": explicit_engine,
        "analysis_points": explicit_engine,
        "extra_innings": explicit_engine,
        "explicit_engine": explicit_engine,
        "no_v13_engine_global_monkeypatches": no_v13_engine_global_monkeypatches,
        "legacy_global_markers": global_markers,
    }


def assert_runtime_hooks() -> dict[str, Any]:
    """Backward-compatible assertion for the new explicit runtime contract."""
    status = runtime_hook_status()
    required = (
        status.get("installed")
        and status.get("explicit_engine")
        and status.get("runner_row")
        and status.get("no_v13_engine_global_monkeypatches")
    )
    if not required:
        raise RuntimeError(f"V13 explicit runtime integration incomplete: {status}")
    return status


def install() -> bool:
    """Install V13 as an explicit engine object plus a persistence adapter.

    No V13 code mutates ``engine_v12.analyze``, ``engine_v12._analysis_points``,
    ``engine_v12.prob_home_win`` or ``methodology_v123.bootstrap_prior_v123``.
    V12.3 remains the compatibility/base layer; V13 orchestration lives in the
    ``V13Engine`` instance assigned to ``runner.engine``.
    """
    global _INSTALLED, _ENGINE
    if _INSTALLED:
        return True

    from . import config, runner

    original_row = runner._row
    engine = V13Engine()

    def row(result, run_id, at, snapshot=None, source_replay=None):
        payload = original_row(result, run_id, at, snapshot, source_replay)
        live = {_option_key(option): option for option in result.get("options") or []}
        for saved in payload.get("options") or []:
            src = live.get(_option_key(saved)) or {}
            for field in V13_OPTION_FIELDS:
                saved[field] = src.get(field)
        payload["data_quality"] = result.get("data_quality")
        payload["shadow_v13_rich_runs"] = result.get("shadow_v13_rich_runs")
        payload["v13_shadow_chain"] = result.get("v13_shadow_chain")
        payload["v13_validation_baseline"] = result.get("v13_validation_baseline")
        payload["v13_validation_baseline_ready"] = result.get("v13_validation_baseline_ready")
        payload["v13_engine"] = result.get("v13_engine")
        attach_contract(payload)
        as_of = str(payload.get("analyzed_at") or at or datetime.now(timezone.utc).isoformat())
        pit.mark_live_snapshot(payload, as_of)
        payload["software_version"] = VERSION
        payload["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION
        payload["model_generation"] = MODEL_GENERATION_FINGERPRINT
        payload["probability_product"] = "baseball-only-calibrated"
        payload["predictive_compatibility_independent_of_software_version"] = True
        payload["predictive_analytics_mode"] = True
        payload["primary_probability_field"] = "p_predictive_final"
        payload["runtime_architecture_contract"] = "v13-explicit-engine-v1"
        return payload

    row._v13_runtime_adapter = True
    runner.engine = engine
    runner._row = row
    config.VERSION = VERSION
    _ENGINE = engine
    _INSTALLED = True
    assert_runtime_hooks()
    return True
