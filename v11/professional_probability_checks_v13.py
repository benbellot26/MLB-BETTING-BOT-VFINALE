from __future__ import annotations

import math
from typing import Any

from . import v13_probability_surface


def _valid_probability(value: Any) -> bool:
    try:
        p=float(value)
    except Exception:
        return False
    return math.isfinite(p) and 0.0 < p < 1.0


def check_option(opt: dict[str,Any]) -> list[str]:
    issues: list[str] = []
    if opt.get("p_baseball_raw") is None:
        issues.append("missing_p_baseball_raw")
    elif not _valid_probability(opt.get("p_baseball_raw")):
        issues.append("invalid_p_baseball_raw")
    if opt.get("p_baseball_calibrated") is None:
        issues.append("missing_p_baseball_calibrated")
    elif not _valid_probability(opt.get("p_baseball_calibrated")):
        issues.append("invalid_p_baseball_calibrated")
    if opt.get("p_predictive_final") is not None and not _valid_probability(opt.get("p_predictive_final")):
        issues.append("invalid_p_predictive_final")
    if opt.get("probability_product") != "calibrated-baseball-only":
        issues.append("wrong_probability_product")
    source = str(opt.get("baseball_probability_source") or "")
    if "market" in source.lower() or "sharp" in source.lower():
        issues.append("market_leakage_source")
    if opt.get("p_effective") is not None and opt.get("p_baseball_calibrated") is not None:
        try:
            if abs(float(opt["p_effective"])-float(opt["p_baseball_calibrated"])) > 1e-9:
                issues.append("legacy_alias_not_baseball_calibrated")
        except Exception:
            issues.append("legacy_alias_invalid")
    return issues


def check_result(result: dict[str,Any]) -> dict[str,Any]:
    option_issues = []
    for i,opt in enumerate(result.get("options") or []):
        issues = check_option(opt)
        if issues:
            option_issues.append({"index":i,"market":opt.get("market"),"name":opt.get("name"),"issues":issues})
    surface_issues=[]
    if result.get("ctx") and len(result.get("options") or []) >= 8:
        try:
            report=v13_probability_surface.validate(result,require_display_surface=True)
            surface_issues=list(report.get("errors") or [])
        except Exception as exc:
            surface_issues=[f"surface_validation_error:{type(exc).__name__}:{exc}"]
    elif result.get("probability_surface_valid") is False:
        surface_issues=list(((result.get("probability_surface") or {}).get("errors")) or ["surface_invalid"])
    return {
        "passes": not option_issues and not surface_issues and result.get("market_blend_allowed_for_edge") is False,
        "option_issues": option_issues,
        "surface_issues":surface_issues,
        "market_blend_allowed_for_edge": result.get("market_blend_allowed_for_edge"),
    }
