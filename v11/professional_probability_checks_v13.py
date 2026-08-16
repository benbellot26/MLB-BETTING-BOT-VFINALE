from __future__ import annotations

from typing import Any


def check_option(opt: dict[str,Any]) -> list[str]:
    issues: list[str] = []
    if opt.get("p_baseball_raw") is None:
        issues.append("missing_p_baseball_raw")
    if opt.get("p_baseball_calibrated") is None:
        issues.append("missing_p_baseball_calibrated")
    if opt.get("probability_product") != "calibrated-baseball-only":
        issues.append("wrong_probability_product")
    source = str(opt.get("baseball_probability_source") or "")
    if "market" in source.lower() or "sharp" in source.lower():
        issues.append("market_leakage_source")
    if opt.get("p_effective") is not None and opt.get("p_baseball_calibrated") is not None:
        if abs(float(opt["p_effective"])-float(opt["p_baseball_calibrated"])) > 1e-9:
            issues.append("legacy_alias_not_baseball_calibrated")
    return issues


def check_result(result: dict[str,Any]) -> dict[str,Any]:
    option_issues = []
    for i,opt in enumerate(result.get("options") or []):
        issues = check_option(opt)
        if issues:
            option_issues.append({"index":i,"market":opt.get("market"),"name":opt.get("name"),"issues":issues})
    return {
        "passes": not option_issues and result.get("market_blend_allowed_for_edge") is False,
        "option_issues": option_issues,
        "market_blend_allowed_for_edge": result.get("market_blend_allowed_for_edge"),
    }
