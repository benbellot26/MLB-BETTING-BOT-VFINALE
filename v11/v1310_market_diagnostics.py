from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .probability_contract_v13 import MODEL_GENERATION_FINGERPRINT, row_is_predictively_compatible

MARKETS = ("ML", "RUNLINE", "TOTAL")
PHASE_RANK = {"EARLY": 0, "LATE": 1, "FINAL": 2}
CHECKPOINT_N = 100
POSTERIOR_MIN_N = 300


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _norm(value: Any) -> str:
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _current(state: dict[str, Any]) -> bool:
    generation = state.get("model_generation") or state.get("model_generation_fingerprint")
    return generation == MODEL_GENERATION_FINGERPRINT and row_is_predictively_compatible(state)


def _result_y(state: dict[str, Any]) -> int | None:
    result = state.get("settled_result") or state.get("result")
    return 1 if result == "WIN" else 0 if result == "LOSS" else None


def _prob(state: dict[str, Any], field: str = "p_predictive_final") -> float | None:
    keys = [field]
    if field == "p_predictive_final":
        keys += ["p_baseball_calibrated", "p_model", "p_effective"]
    elif field == "p_baseball_calibrated":
        keys += ["p_model", "p_effective"]
    for key in keys:
        value = _num(state.get(key))
        if value is not None:
            return max(.001, min(.999, value))
    return None


def _obs_rank(state: dict[str, Any]) -> tuple[int, str]:
    phase = str(state.get("phase") or state.get("observation_phase") or "EARLY").upper()
    at = str(state.get("observation_at") or state.get("observed_at") or state.get("analyzed_at") or "")
    return PHASE_RANK.get(phase, -1), at


def _independent_key(state: dict[str, Any]) -> tuple[str, str, str]:
    gid = str(state.get("game_pk") or "")
    market = str(state.get("market") or "").upper()
    point = _num(state.get("point"))
    if market == "ML":
        token = "game"
    elif market == "RUNLINE":
        token = f"{abs(point or 0):g}"
    else:
        token = "none" if point is None else f"{point:g}"
    return gid, market, token


def _choose_side(states: list[dict[str, Any]]) -> dict[str, Any]:
    market = str(states[0].get("market") or "").upper()
    canonical = [s for s in states if s.get("canonical") or s.get("is_canonical_line")]
    pool = canonical or states
    if market == "TOTAL":
        pick = next((s for s in pool if str(s.get("pick") or s.get("name") or "").lower() == "over"), None)
    else:
        home = str(pool[0].get("home") or "")
        pick = next((s for s in pool if _norm(s.get("pick") or s.get("name")) == _norm(home)), None)
    return pick or sorted(pool, key=lambda s: (str(s.get("pick") or s.get("name") or ""), str(s.get("point") or "")))[0]


def canonical_states(states: list[dict[str, Any]], market: str | None = None, phase: str | None = None) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for state in states:
        if not state.get("game_pk") or not _current(state):
            continue
        if (state.get("settled_result") or state.get("result")) not in {"WIN", "LOSS", "PUSH"}:
            continue
        state_market = str(state.get("market") or "").upper()
        if market and state_market != str(market).upper():
            continue
        state_phase = str(state.get("phase") or state.get("observation_phase") or "EARLY").upper()
        if phase and state_phase != str(phase).upper():
            continue
        groups[_independent_key(state)].append(state)
    chosen = []
    for group in groups.values():
        latest = max(_obs_rank(state) for state in group)
        same = [state for state in group if _obs_rank(state) == latest]
        chosen.append(_choose_side(same))
    return sorted(chosen, key=lambda s: (str(s.get("game_date") or s.get("target_date") or ""), str(s.get("game_pk") or ""), str(s.get("market") or "")))


def _ece(rows: list[tuple[float, float]]) -> float | None:
    if not rows:
        return None
    total = 0.0
    n = len(rows)
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10 if i < 9 else 1.001
        bucket = [(p, y) for p, y in rows if lo <= p < hi]
        if not bucket:
            continue
        mean_p = sum(p for p, _ in bucket) / len(bucket)
        outcome = sum(y for _, y in bucket) / len(bucket)
        total += len(bucket) / n * abs(mean_p - outcome)
    return round(total, 6)


def probability_metrics(states: list[dict[str, Any]], field: str = "p_predictive_final") -> dict[str, Any]:
    scored: list[tuple[float, float]] = []
    pushes = 0
    for state in states:
        result = state.get("settled_result") or state.get("result")
        if result == "PUSH":
            pushes += 1
            continue
        y = _result_y(state)
        p = _prob(state, field)
        if y is None or p is None:
            continue
        scored.append((p, float(y)))
    if not scored:
        return {"n": 0, "pushes": pushes}
    n = len(scored)
    brier = sum((p - y) ** 2 for p, y in scored) / n
    logloss = sum(-(y * math.log(p) + (1 - y) * math.log(1 - p)) for p, y in scored) / n
    mean_p = sum(p for p, _ in scored) / n
    outcome = sum(y for _, y in scored) / n
    return {
        "n": n,
        "pushes": pushes,
        "brier": round(brier, 6),
        "logloss": round(logloss, 6),
        "ece": _ece(scored),
        "mean_probability": round(mean_p, 6),
        "outcome_rate": round(outcome, 6),
        "calibration_gap": round(mean_p - outcome, 6),
        "accuracy_at_50": round(sum((p >= .5) == bool(y) for p, y in scored) / n, 6),
    }


def _dq_score(state: dict[str, Any]) -> float | None:
    dq = state.get("data_quality")
    if isinstance(dq, dict):
        return _num(dq.get("model_input_score", dq.get("score")))
    return _num(dq)


def _dq_band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < .60:
        return "<0.60"
    if score < .75:
        return "0.60-0.75"
    if score < .90:
        return "0.75-0.90"
    return ">=0.90"


def market_scorecard(states: list[dict[str, Any]]) -> dict[str, Any]:
    return {market: probability_metrics(canonical_states(states, market)) for market in MARKETS}


def phase_scorecard(states: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        market: {phase: probability_metrics(canonical_states(states, market, phase)) for phase in ("EARLY", "LATE", "FINAL")}
        for market in MARKETS
    }


def dq_scorecard(states: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for market in MARKETS:
        rows = canonical_states(states, market)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for state in rows:
            grouped[_dq_band(_dq_score(state))].append(state)
        out[market] = {band: probability_metrics(group) for band, group in sorted(grouped.items())}
    return out


def _paired_improvement(states: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [s for s in states if _prob(s, "p_baseball_calibrated") is not None and _prob(s, "p_posterior") is not None and _result_y(s) is not None]
    if not paired:
        return {"n": 0, "brier_improvement": None, "logloss_improvement": None, "status": "COLLECTING", "required_n": POSTERIOR_MIN_N}
    base = probability_metrics(paired, "p_baseball_calibrated")
    posterior = probability_metrics(paired, "p_posterior")
    n = int(base.get("n") or 0)
    return {
        "n": n,
        "brier_improvement": round(float(base["brier"]) - float(posterior["brier"]), 6),
        "logloss_improvement": round(float(base["logloss"]) - float(posterior["logloss"]), 6),
        "baseball": base,
        "posterior": posterior,
        "status": "READY_FOR_EVIDENCE_REVIEW" if n >= POSTERIOR_MIN_N else "COLLECTING",
        "required_n": POSTERIOR_MIN_N,
    }


def posterior_monitor(states: list[dict[str, Any]]) -> dict[str, Any]:
    return {market: _paired_improvement(canonical_states(states, market)) for market in MARKETS}


def _total_line_band(point: float | None) -> str:
    if point is None:
        return "unknown"
    if point <= 7.5:
        return "<=7.5"
    if point <= 8.5:
        return "8.0-8.5"
    if point <= 9.5:
        return "9.0-9.5"
    return ">=10.0"


def _gap_band(gap: float) -> str:
    if gap <= -2:
        return "<=-2"
    if gap <= -1:
        return "-2/-1"
    if gap < 0:
        return "-1/0"
    if gap < 1:
        return "0/1"
    if gap < 2:
        return "1/2"
    return ">=2"


def total_diagnostics(states: list[dict[str, Any]]) -> dict[str, Any]:
    rows = canonical_states(states, "TOTAL")
    by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_gap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    projection_errors = []
    for state in rows:
        point = _num(state.get("point"))
        by_line[_total_line_band(point)].append(state)
        projected = _num(state.get("projected_total_runs"))
        if projected is None:
            hp, ap = _num(state.get("projected_home_runs")), _num(state.get("projected_away_runs"))
            if hp is not None and ap is not None:
                projected = hp + ap
        hs, ass = _num(state.get("home_score")), _num(state.get("away_score"))
        if projected is not None and point is not None:
            by_gap[_gap_band(projected - point)].append(state)
        if projected is not None and hs is not None and ass is not None:
            projection_errors.append((hs + ass) - projected)
    projection = {"n": len(projection_errors)}
    if projection_errors:
        projection.update({
            "mae_runs": round(sum(abs(x) for x in projection_errors) / len(projection_errors), 4),
            "bias_runs": round(sum(projection_errors) / len(projection_errors), 4),
        })
    return {
        "overall": probability_metrics(rows),
        "projection": projection,
        "by_market_line": {band: probability_metrics(group) for band, group in sorted(by_line.items())},
        "by_projected_total_minus_line": {band: probability_metrics(group) for band, group in sorted(by_gap.items())},
    }


def _margin_band(value: float) -> str:
    x = abs(value)
    if x < 1:
        return "<1"
    if x < 2:
        return "1-2"
    if x < 3:
        return "2-3"
    return ">=3"


def runline_diagnostics(states: list[dict[str, Any]]) -> dict[str, Any]:
    rows = canonical_states(states, "RUNLINE")
    by_margin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    margin_errors = []
    for state in rows:
        margin = _num(state.get("projected_margin_runs"))
        if margin is None:
            hp, ap = _num(state.get("projected_home_runs")), _num(state.get("projected_away_runs"))
            if hp is not None and ap is not None:
                margin = hp - ap
        hs, ass = _num(state.get("home_score")), _num(state.get("away_score"))
        if margin is not None:
            by_margin[_margin_band(margin)].append(state)
        if margin is not None and hs is not None and ass is not None:
            margin_errors.append((hs - ass) - margin)
    projection = {"n": len(margin_errors)}
    if margin_errors:
        projection.update({
            "mae_runs": round(sum(abs(x) for x in margin_errors) / len(margin_errors), 4),
            "bias_runs": round(sum(margin_errors) / len(margin_errors), 4),
        })
    return {
        "overall": probability_metrics(rows),
        "projected_margin": projection,
        "by_abs_projected_margin": {band: probability_metrics(group) for band, group in sorted(by_margin.items())},
    }


def checkpoint(states: list[dict[str, Any]], target: int = CHECKPOINT_N) -> dict[str, Any]:
    ml = canonical_states(states, "ML")
    games = len({str(s.get("game_pk")) for s in ml})
    if not games:
        games = len({str(s.get("game_pk")) for s in canonical_states(states)})
    return {
        "unique_games": games,
        "target": target,
        "remaining": max(0, target - games),
        "progress_pct": round(min(1.0, games / max(1, target)) * 100, 1),
        "status": "READY_FOR_REVIEW" if games >= target else "COLLECTING",
    }


def states_from_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = []
    for row in games:
        contract = row.get("predictive_contract") or {}
        generation = row.get("model_generation") or row.get("model_generation_fingerprint")
        for option in row.get("options") or []:
            states.append({
                "game_pk": row.get("game_pk"),
                "target_date": row.get("target_date"),
                "game_date": row.get("game_date"),
                "analyzed_at": row.get("analyzed_at"),
                "observation_at": row.get("analyzed_at"),
                "phase": row.get("phase"),
                "home": row.get("home"),
                "away": row.get("away"),
                "home_score": row.get("home_score"),
                "away_score": row.get("away_score"),
                "projected_home_runs": row.get("projected_home_runs"),
                "projected_away_runs": row.get("projected_away_runs"),
                "projected_total_runs": (_num(row.get("projected_home_runs")) + _num(row.get("projected_away_runs"))) if _num(row.get("projected_home_runs")) is not None and _num(row.get("projected_away_runs")) is not None else None,
                "projected_margin_runs": (_num(row.get("projected_home_runs")) - _num(row.get("projected_away_runs"))) if _num(row.get("projected_home_runs")) is not None and _num(row.get("projected_away_runs")) is not None else None,
                "model_generation": generation,
                "predictive_contract": contract,
                "market": option.get("market"),
                "pick": option.get("name"),
                "point": option.get("point"),
                "canonical": bool(option.get("is_canonical_line")),
                "p_predictive_final": option.get("p_predictive_final"),
                "p_baseball_calibrated": option.get("p_baseball_calibrated", option.get("p_effective")),
                "p_posterior": option.get("p_posterior"),
                "p_model": option.get("p_model", option.get("p_effective")),
                "data_quality": option.get("data_quality", row.get("data_quality")),
                "settled_result": option.get("result"),
            })
    return states


def enrich_with_games(states: list[dict[str, Any]], games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = {str(row.get("game_pk")): row for row in games if row.get("game_pk")}
    out = []
    for state in states:
        item = dict(state)
        row = lookup.get(str(item.get("game_pk") or "")) or {}
        hp, ap = _num(row.get("projected_home_runs")), _num(row.get("projected_away_runs"))
        if item.get("projected_home_runs") is None and hp is not None:
            item["projected_home_runs"] = hp
        if item.get("projected_away_runs") is None and ap is not None:
            item["projected_away_runs"] = ap
        if item.get("projected_total_runs") is None and hp is not None and ap is not None:
            item["projected_total_runs"] = hp + ap
        if item.get("projected_margin_runs") is None and hp is not None and ap is not None:
            item["projected_margin_runs"] = hp - ap
        if item.get("home_score") is None:
            item["home_score"] = row.get("home_score")
        if item.get("away_score") is None:
            item["away_score"] = row.get("away_score")
        if item.get("data_quality") is None:
            item["data_quality"] = row.get("data_quality")
        out.append(item)
    return out


def build(states: list[dict[str, Any]], games: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    prepared = enrich_with_games(list(states), list(games or []))
    return {
        "scope": "current-generation-only; one latest pregame side per unique game+market line",
        "by_market": market_scorecard(prepared),
        "by_phase": phase_scorecard(prepared),
        "by_data_quality": dq_scorecard(prepared),
        "runline": runline_diagnostics(prepared),
        "total": total_diagnostics(prepared),
        "posterior_shadow": posterior_monitor(prepared),
        "checkpoint_100": checkpoint(prepared),
        "changes_predictions": False,
    }
