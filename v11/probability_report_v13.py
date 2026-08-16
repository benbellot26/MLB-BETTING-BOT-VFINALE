from __future__ import annotations

from typing import Any


def _pct(value: Any) -> str:
    try:
        return f"{100*float(value):.1f}%"
    except Exception:
        return "—"


def option_summary(opt: dict[str,Any]) -> dict[str,Any]:
    return {
        "market": opt.get("market"),
        "pick": opt.get("name"),
        "point": opt.get("point"),
        "baseball_raw": opt.get("p_baseball_raw"),
        "baseball_calibrated": opt.get("p_baseball_calibrated"),
        "sharp_probability": opt.get("p_market"),
        "posterior_forecast_only": opt.get("p_posterior"),
        "model_market_gap": opt.get("model_market_gap"),
        "interval_low": opt.get("probability_interval_low"),
        "interval_high": opt.get("probability_interval_high"),
        "push": opt.get("p_push"),
        "calibration_source": opt.get("calibration_source_v13"),
        "calibration_n": opt.get("calibration_n_v13"),
    }


def text_line(opt: dict[str,Any]) -> str:
    name = str(opt.get("name") or "")
    point = "" if opt.get("point") is None else f" {opt.get('point'):+g}" if isinstance(opt.get("point"),(int,float)) else f" {opt.get('point')}"
    gap = opt.get("model_market_gap")
    gap_txt = "—" if gap is None else f"{100*float(gap):+.1f}pp"
    low,high = opt.get("probability_interval_low"),opt.get("probability_interval_high")
    interval = "—" if low is None or high is None else f"{_pct(low)}–{_pct(high)}"
    push = opt.get("p_push")
    push_txt = "" if not push else f" • push {_pct(push)}"
    return (
        f"{opt.get('market')} {name}{point} • baseball {_pct(opt.get('p_baseball_calibrated'))} "
        f"(raw {_pct(opt.get('p_baseball_raw'))}) • sharp {_pct(opt.get('p_market'))} • gap {gap_txt} "
        f"• interval 90% {interval}{push_txt}"
    )


def game_report(result: dict[str,Any]) -> dict[str,Any]:
    ctx = result.get("ctx") or {}
    return {
        "game_pk": result.get("game_pk"),
        "game": f"{ctx.get('away','')} @ {ctx.get('home','')}",
        "phase": result.get("phase"),
        "run_projection": {"home":result.get("hmu"),"away":result.get("amu")},
        "probability_product":"baseball-only-calibrated",
        "options":[option_summary(o) for o in result.get("options") or [] if o.get("p_baseball_calibrated") is not None],
    }
