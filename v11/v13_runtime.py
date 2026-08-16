from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from . import calibration_baseball_v13 as calibration
from . import point_in_time_v13 as pit
from .probability_contract_v13 import attach_contract, option_contract_payload, assert_no_market_leakage

VERSION = "13.0-professional-probability-v1"
_INSTALLED = False


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def _clip(p: Any) -> float:
    return max(.001, min(.999, _num(p, .5)))


def _interval(p: float, uncertainty: float, calibration_n: int) -> tuple[float,float]:
    # Conservative empirical interval. With sparse calibration evidence the
    # interval widens; it is deliberately not presented as a parametric truth.
    base = max(.015, min(.14, _num(uncertainty, .06)))
    sample_penalty = .06 if calibration_n <= 0 else min(.06, 1.0/math.sqrt(max(1, calibration_n)))
    half = min(.22, 1.645*math.sqrt(base*base + sample_penalty*sample_penalty))
    return max(.001, p-half), min(.999, p+half)


def _posterior(calibrated: float, market: float | None, market_weight: float) -> float | None:
    if market is None:
        return None
    # Forecasting-only posterior. It is never allowed to define edge/value.
    w = max(0.0, min(.35, _num(market_weight, 0.0)))
    return _clip((1-w)*calibrated + w*_clip(market))


def _baseball_raw(opt: dict[str,Any]) -> float:
    # p_learned in the current V12.3 engine is computed before sharp blending.
    # Fall back only to structural baseball, never p_model/p_effective.
    if opt.get("p_learned") is not None:
        return _clip(opt.get("p_learned"))
    if opt.get("p_structural") is not None:
        return _clip(opt.get("p_structural"))
    raise ValueError("No baseball-only probability available")


def upgrade_option(opt: dict[str,Any], phase: str, model: dict[str,Any]) -> dict[str,Any]:
    raw = _baseball_raw(opt)
    calibrated, source, n = calibration.calibrate(raw, str(opt.get("market") or "ML"), phase, model)
    market = _clip(opt["p_market"]) if opt.get("p_market") is not None else None
    posterior = _posterior(calibrated, market, _num(opt.get("sharp_weight"), 0.0))
    low, high = _interval(calibrated, _num(opt.get("model_uncertainty"), .06), n)
    legacy_effective = opt.get("p_effective")
    payload = option_contract_payload(
        p_baseball_raw=raw,
        p_baseball_calibrated=calibrated,
        p_market=market,
        p_posterior=posterior,
        calibration_source=source,
        calibration_n=n,
        interval_low=low,
        interval_high=high,
    )
    opt["p_legacy_market_blended"] = legacy_effective
    opt.update(payload)
    # Downstream legacy selector/report code reads p_effective/p_win. In V13 these
    # aliases intentionally point to baseball-only calibrated probability.
    push = max(0.0, min(.35, _num(opt.get("p_push_model", opt.get("p_push")), 0.0)))
    opt["p_effective"] = round(calibrated, 6)
    opt["p_model"] = round(raw, 6)
    opt["p_win"] = round(calibrated*(1-push), 6)
    opt["p_push"] = round(push, 6)
    opt["probability_product"] = "calibrated-baseball-only"
    assert_no_market_leakage(opt)
    return opt


def upgrade_result(result: dict[str,Any], model: dict[str,Any] | None = None) -> dict[str,Any]:
    model = calibration.load_model() if model is None else model
    phase = str(result.get("phase") or "EARLY").upper()
    for opt in result.get("options") or []:
        try:
            upgrade_option(opt, phase, model)
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
    return result


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    from . import config, engine_v12, runner

    original_analyze = engine_v12.analyze
    original_row = runner._row

    def analyze(game, event, as_of=None):
        result = original_analyze(game, event, as_of=as_of)
        return upgrade_result(result)

    def row(result, run_id, at, snapshot=None, source_replay=None):
        payload = original_row(result, run_id, at, snapshot, source_replay)
        attach_contract(payload)
        as_of = str(payload.get("analyzed_at") or at or datetime.now(timezone.utc).isoformat())
        # Production rows are backed by the run's recorded/replayed HTTP sources.
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
