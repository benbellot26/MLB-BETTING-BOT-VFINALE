from __future__ import annotations

import math
from typing import Any

TOLERANCE = 2e-6


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _finite_probability(value: Any, field: str) -> float:
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"{field} is not numeric") from exc
    if not math.isfinite(out) or not 0.0 < out < 1.0:
        raise ValueError(f"{field} must be finite and strictly between 0 and 1")
    return out


def _point(option: dict[str, Any]) -> float | None:
    value = option.get("point")
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _prob(option: dict[str, Any]) -> float:
    for field in ("p_baseball_calibrated", "p_predictive_final", "p_effective"):
        if option.get(field) is not None:
            return _finite_probability(option[field], field)
    raise ValueError("option missing calibrated probability")


def _shift_interval(option: dict[str, Any], old: float, new: float) -> None:
    low = option.get("probability_interval_low")
    high = option.get("probability_interval_high")
    if low is None or high is None:
        return
    try:
        lo = float(low)
        hi = float(high)
    except Exception:
        return
    if not math.isfinite(lo) or not math.isfinite(hi):
        return
    delta = new - old
    lo = max(.001, min(.999, lo + delta))
    hi = max(.001, min(.999, hi + delta))
    if lo > hi:
        lo, hi = hi, lo
    option["probability_interval_low"] = round(lo, 6)
    option["probability_interval_high"] = round(hi, 6)


def _write_probability(option: dict[str, Any], probability: float) -> None:
    old = _prob(option)
    p = _finite_probability(probability, "reconciled_probability")
    _shift_interval(option, old, p)
    option["p_baseball_calibrated"] = round(p, 6)
    option["p_predictive_final"] = round(p, 6)
    option["p_effective"] = round(p, 6)
    push = option.get("p_push_model", option.get("p_push", 0.0))
    try:
        push_value = float(push or 0.0)
    except Exception:
        push_value = 0.0
    if not math.isfinite(push_value):
        push_value = 0.0
    push_value = max(0.0, min(.95, push_value))
    option["p_push"] = round(push_value, 6)
    option["p_win"] = round(p * (1.0 - push_value), 6)
    market = option.get("p_market")
    if market is not None:
        try:
            market_p = float(market)
            if math.isfinite(market_p) and 0.0 < market_p < 1.0:
                option["model_market_gap"] = round(p - market_p, 6)
                weight = float(option.get("posterior_weight_v13") or 0.0)
                weight = max(0.0, min(1.0, weight))
                if option.get("p_posterior") is not None:
                    option["p_posterior"] = round((1.0 - weight) * p + weight * market_p, 6)
        except Exception:
            pass
    option["calibration_surface_reconciled"] = True


def _normalize_pair(first: dict[str, Any], second: dict[str, Any]) -> None:
    a = _prob(first)
    b = _prob(second)
    total = a + b
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("complementary probability pair has invalid mass")
    pa = a / total
    pb = 1.0 - pa
    _write_probability(first, pa)
    _write_probability(second, pb)


def _find_team(options: list[dict[str, Any]], market: str, team: str, point: float | None = None):
    target = _norm(team)
    for option in options:
        if str(option.get("market") or "").upper() != market:
            continue
        if _norm(option.get("name")) != target:
            continue
        if point is not None:
            value = _point(option)
            if value is None or abs(value - point) > 1e-6:
                continue
        return option
    return None


def _total_pairs(options: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_point: dict[float, dict[str, dict[str, Any]]] = {}
    for option in options:
        if str(option.get("market") or "").upper() != "TOTAL":
            continue
        point = _point(option)
        side = str(option.get("name") or "").lower()
        if point is None or side not in {"over", "under"}:
            continue
        by_point.setdefault(point, {})[side] = option
    return [(sides["over"], sides["under"]) for sides in by_point.values() if {"over", "under"} <= set(sides)]


def _canonical_total_pair(result: dict[str, Any]) -> tuple[float | None, dict[str, Any] | None, dict[str, Any] | None]:
    options = list(result.get("options") or [])
    canonical = (result.get("canonical_lines") or {}).get("TOTAL")
    if canonical is not None:
        try:
            point = float(canonical)
        except Exception:
            point = None
        if point is not None and math.isfinite(point):
            over = next((o for o in options if str(o.get("market") or "").upper() == "TOTAL"
                         and str(o.get("name") or "").lower() == "over"
                         and _point(o) is not None and abs(float(_point(o)) - point) <= 1e-6), None)
            under = next((o for o in options if str(o.get("market") or "").upper() == "TOTAL"
                          and str(o.get("name") or "").lower() == "under"
                          and _point(o) is not None and abs(float(_point(o)) - point) <= 1e-6), None)
            if over is not None or under is not None:
                return point, over, under
    pairs = []
    for over, under in _total_pairs(options):
        point = _point(over)
        if point is not None:
            pairs.append((point, over, under))
    if not pairs:
        return None, None, None
    pairs.sort(key=lambda row: row[0])
    return pairs[len(pairs) // 2]


def reconcile(result: dict[str, Any]) -> dict[str, Any]:
    """Reconcile every complementary binary market after calibration.

    Calibration methods are intentionally free to be nonlinear. Applying a
    nonlinear transform independently to both sides can make complementary
    probabilities sum to something other than 1. This pass preserves their
    relative calibrated strength while restoring an exact probability surface.
    """
    options = list(result.get("options") or [])
    ctx = result.get("ctx") or {}
    home = str(ctx.get("home") or "")
    away = str(ctx.get("away") or "")

    home_ml = _find_team(options, "ML", home)
    away_ml = _find_team(options, "ML", away)
    if home_ml is not None and away_ml is not None:
        _normalize_pair(home_ml, away_ml)

    seen: set[tuple[str, float]] = set()
    for option in options:
        if str(option.get("market") or "").upper() != "RUNLINE":
            continue
        point = _point(option)
        if point is None:
            continue
        name = str(option.get("name") or "")
        if _norm(name) == _norm(home):
            other = _find_team(options, "RUNLINE", away, -point)
        elif _norm(name) == _norm(away):
            other = _find_team(options, "RUNLINE", home, -point)
        else:
            continue
        if other is None:
            continue
        canonical_key = tuple(sorted((_norm(name) + f":{point:.6f}", _norm(other.get("name")) + f":{-point:.6f}")))
        marker = ("|".join(canonical_key), 0.0)
        if marker in seen:
            continue
        seen.add(marker)
        _normalize_pair(option, other)

    for over, under in _total_pairs(options):
        _normalize_pair(over, under)

    report = validate(result)
    result["probability_surface"] = report
    return report


def validate(result: dict[str, Any], require_display_surface: bool = False) -> dict[str, Any]:
    options = list(result.get("options") or [])
    ctx = result.get("ctx") or {}
    home = str(ctx.get("home") or "")
    away = str(ctx.get("away") or "")
    errors: list[str] = []

    for option in options:
        if option.get("p_baseball_calibrated") is None:
            continue
        try:
            _prob(option)
        except ValueError as exc:
            errors.append(f"non_finite_probability:{option.get('market')}:{option.get('name')}:{exc}")

    home_ml = _find_team(options, "ML", home)
    away_ml = _find_team(options, "ML", away)
    if home_ml is None or away_ml is None:
        errors.append("ml_pair_missing")
    elif abs((_prob(home_ml) + _prob(away_ml)) - 1.0) > TOLERANCE:
        errors.append("ml_not_complementary")

    standard = {}
    for team_name, label in ((home, "home"), (away, "away")):
        plus = _find_team(options, "RUNLINE", team_name, 1.5)
        minus = _find_team(options, "RUNLINE", team_name, -1.5)
        standard[(label, 1.5)] = plus
        standard[(label, -1.5)] = minus
        if plus is None or minus is None:
            errors.append(f"runline_standard_missing:{label}")
        elif _prob(plus) + TOLERANCE < _prob(minus):
            errors.append(f"runline_monotonicity:{label}")
    if standard.get(("home", -1.5)) is not None and standard.get(("away", 1.5)) is not None:
        if abs(_prob(standard[("home", -1.5)]) + _prob(standard[("away", 1.5)]) - 1.0) > TOLERANCE:
            errors.append("runline_home_minus_pair_not_complementary")
    if standard.get(("home", 1.5)) is not None and standard.get(("away", -1.5)) is not None:
        if abs(_prob(standard[("home", 1.5)]) + _prob(standard[("away", -1.5)]) - 1.0) > TOLERANCE:
            errors.append("runline_home_plus_pair_not_complementary")

    total_options = [o for o in options if str(o.get("market") or "").upper() == "TOTAL"]
    canonical_total = (result.get("canonical_lines") or {}).get("TOTAL")
    analysis_total = ((result.get("analysis_lines") or {}).get("TOTAL") or {})
    total_expected = bool(total_options or canonical_total is not None or (analysis_total.get("points") or []))
    total_point, over, under = _canonical_total_pair(result)
    if total_expected:
        if over is None or under is None:
            errors.append("canonical_total_pair_missing")
        elif abs(_prob(over) + _prob(under) - 1.0) > TOLERANCE:
            errors.append("canonical_total_not_complementary")

    display_complete = not any(
        error.startswith(("ml_pair_missing", "runline_standard_missing", "canonical_total_pair_missing"))
        for error in errors
    )
    if require_display_surface and not display_complete:
        errors.append("display_surface_incomplete")
    return {
        "schema": "v13-probability-surface-v1",
        "valid": not errors,
        "display_complete": display_complete,
        "canonical_total_point": total_point,
        "total_market_expected": total_expected,
        "total_market_available": bool(total_options),
        "errors": sorted(set(errors)),
        "contract": "ML and available complementary RL/TOTAL pairs sum to 1; standard +/-1.5 probabilities are monotone",
    }


def assert_valid(result: dict[str, Any], require_display_surface: bool = False) -> dict[str, Any]:
    report = validate(result, require_display_surface=require_display_surface)
    if not report["valid"]:
        raise ValueError("invalid V13 probability surface: " + ",".join(report["errors"]))
    return report
