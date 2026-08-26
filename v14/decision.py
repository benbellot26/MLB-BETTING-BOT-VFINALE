from __future__ import annotations

"""Fail-closed betting-decision diagnostics for Pulsar V14.

This layer is not permitted to emit BET while the statistical certification is
false. It still marks edge-qualified research candidates so prospective CLV can
be collected without creating a circular certification dependency.
"""

import math
from typing import Any

MIN_ROBUST_EDGE_PP = 2.0
MIN_MODEL_EDGE_PP = 3.0

SELECTIONS = {
    "ML": {"home": "home_ml", "away": "away_ml"},
    "RL": {"home_-1.5": "home_minus_1_5", "away_+1.5": "away_plus_1_5", "away_-1.5": "away_minus_1_5", "home_+1.5": "home_plus_1_5"},
    "TOTAL": {"over": "over", "under": "under"},
}
CALIBRATION_MARKET = {
    "home_ml": "ML", "away_ml": "ML",
    "home_minus_1_5": "RL_HOME_-1.5", "away_plus_1_5": "RL_HOME_-1.5",
    "away_minus_1_5": "RL_AWAY_-1.5", "home_plus_1_5": "RL_AWAY_-1.5",
    "over": "TOTAL_OVER", "under": "TOTAL_OVER",
}


def _num(value: Any) -> float | None:
    try: out = float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _execution_rows(snapshot: dict[str, Any]) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []; markets = snapshot.get("markets") or {}
    for market, mapping in SELECTIONS.items():
        block = markets.get(market) or {}; selections = block.get("selections") or {}
        for label, key in mapping.items():
            raw = selections.get(label) or {}; price = _num(raw.get("price"))
            if price and price > 1: rows.append((key, market, price))
    return rows


def evaluate(*, prediction: dict[str, Any], market_snapshot: dict[str, Any], sharp_market: dict[str, Any], certification: dict[str, Any], starter_degraded: bool = False) -> dict[str, Any]:
    probs = prediction.get("probabilities") or {}; intervals = (prediction.get("probability_intervals") or {}).get("selections") or {}; calibration = prediction.get("calibration") or {}; sharp = sharp_market.get("selections") or {}; freshness = market_snapshot.get("freshness_verified") is True and sharp_market.get("freshness_verified") is True; globally_certified = certification.get("certified") is True; rows: list[dict[str, Any]] = []
    for key, market, price in _execution_rows(market_snapshot):
        p = _num(probs.get(key))
        if p is None: continue
        lower = _num((intervals.get(key) or {}).get("lower")); lower = lower if lower is not None else max(0.0, p - 0.10); breakeven = 1 / price; sharp_p = _num((sharp.get(key) or {}).get("fair_probability")); model_edge = 100 * (p - breakeven); robust_edge = 100 * (lower - breakeven); sharp_edge = 100 * (p - sharp_p) if sharp_p is not None else None; blockers: list[str] = []
        if starter_degraded: blockers.append("starter_degraded")
        if not freshness: blockers.append("unverified_market_freshness")
        cal_market = CALIBRATION_MARKET.get(key); cal_meta = (calibration.get("markets") or {}).get(cal_market or "") or {}
        if cal_meta.get("active") is not True: blockers.append("calibration_not_active")
        if sharp_p is None: blockers.append("sharp_consensus_missing")
        edge_qualified = model_edge >= MIN_MODEL_EDGE_PP and robust_edge >= MIN_ROBUST_EDGE_PP and sharp_edge is not None and sharp_edge > 0
        research_ready = edge_qualified and not any(x in blockers for x in ("starter_degraded", "unverified_market_freshness", "calibration_not_active", "sharp_consensus_missing"))
        if not globally_certified: blockers.append("betting_not_certified")
        status = "BET" if edge_qualified and not blockers else ("RESEARCH_ONLY" if research_ready else "NO_BET")
        rows.append({"selection": key, "market": market, "price": price, "probability": p, "lower_probability": lower, "break_even_probability": breakeven, "model_edge_pp": model_edge, "robust_edge_pp": robust_edge, "sharp_edge_pp": sharp_edge, "edge_qualified": edge_qualified, "research_ready": research_ready, "status": status, "blockers": blockers})
    rows.sort(key=lambda r: (r.get("robust_edge_pp") or -999), reverse=True)
    return {"schema": "pulsar-v14-decision-diagnostics-v2", "betting_certified": globally_certified, "starter_degraded": bool(starter_degraded), "market_freshness_verified": freshness, "recommendations_authorized": globally_certified, "research_clv_collection_authorized": True, "candidates": rows, "best": rows[0] if rows else None}
