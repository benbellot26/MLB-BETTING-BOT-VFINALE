from __future__ import annotations

"""Post-prediction market diagnostics for Pulsar V14.

Market prices are diagnostic-only. They are evaluated after the independent
baseball probability surface has been produced and are never fed back as model
features.
"""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def odds_to_decimal(odds: Any) -> float:
    value = _num(odds)
    if value is None:
        raise ValueError("odds must be numeric")
    if 1.01 <= value < 20.0:
        return value
    if value >= 100:
        return 1.0 + value / 100.0
    if value <= -100:
        return 1.0 + 100.0 / abs(value)
    raise ValueError("unsupported odds format")


def implied_probability(odds: Any) -> float:
    return 1.0 / odds_to_decimal(odds)


def remove_vig_two_way(odds_a: Any, odds_b: Any) -> tuple[float, float]:
    a, b = implied_probability(odds_a), implied_probability(odds_b)
    total = a + b
    if total <= 0:
        raise ValueError("invalid two-way market")
    return a / total, b / total


def fair_decimal(probability: Any) -> float:
    p = _num(probability)
    if p is None or not 0 < p < 1:
        raise ValueError("probability must be in (0,1)")
    return 1.0 / p


def edge_report(
    model_probability: Any,
    selection_odds: Any,
    opposite_odds: Any | None = None,
) -> dict[str, Any]:
    p_model = _num(model_probability)
    if p_model is None or not 0 <= p_model <= 1:
        raise ValueError("model_probability must be in [0,1]")
    decimal = odds_to_decimal(selection_odds)
    raw_market = 1.0 / decimal
    no_vig = remove_vig_two_way(selection_odds, opposite_odds)[0] if opposite_odds is not None else raw_market
    edge = p_model - no_vig
    return {
        "model_probability": p_model,
        "market_implied_probability": raw_market,
        "market_no_vig_probability": no_vig,
        "edge": edge,
        "edge_pp": edge * 100.0,
        "fair_decimal_odds": fair_decimal(p_model) if 0 < p_model < 1 else None,
        "selection_decimal_odds": decimal,
        "expected_value_per_unit": p_model * decimal - 1.0,
        "market_probability_used_as_feature": False,
    }


def diagnostics_from_snapshot(prediction: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build paired no-vig edge/EV diagnostics from a canonical market snapshot."""
    probabilities = prediction.get("probabilities") or {}
    markets = snapshot.get("markets") or {}
    out: dict[str, Any] = {
        "schema": "pulsar-v14-market-diagnostics-v1",
        "market_probability_used_as_feature": False,
        "markets": {},
    }

    def paired(market_name: str, left_key: str, right_key: str, left_prob: str, right_prob: str) -> None:
        market = markets.get(market_name) or {}
        selections = market.get("selections") or {}
        left = selections.get(left_key) or {}
        right = selections.get(right_key) or {}
        lp, rp = _num(left.get("price")), _num(right.get("price"))
        lmodel, rmodel = _num(probabilities.get(left_prob)), _num(probabilities.get(right_prob))
        if None in {lp, rp, lmodel, rmodel}:
            return
        out["markets"].setdefault(market_name, {
            "bookmaker": market.get("bookmaker"),
            "last_update": market.get("last_update"),
            "age_minutes": market.get("age_minutes"),
            "selections": {},
        })
        out["markets"][market_name]["selections"][left_key] = edge_report(lmodel, lp, rp)
        out["markets"][market_name]["selections"][right_key] = edge_report(rmodel, rp, lp)

    paired("ML", "home", "away", "home_ml", "away_ml")

    rl = markets.get("RL") or {}
    rl_sel = rl.get("selections") or {}
    rl_pairs = (
        ("home_-1.5", "away_+1.5", "home_minus_1_5", "away_plus_1_5"),
        ("away_-1.5", "home_+1.5", "away_minus_1_5", "home_plus_1_5"),
    )
    for a, b, pa, pb in rl_pairs:
        if a in rl_sel and b in rl_sel:
            paired("RL", a, b, pa, pb)

    paired("TOTAL", "over", "under", "over", "under")
    return out


def make_tracking_record(
    *,
    game_pk: Any,
    market: str,
    selection: str,
    model_probability: Any,
    selection_odds: Any,
    opposite_odds: Any | None = None,
    model_version: str = MODEL_GENERATION,
    prediction_timestamp: str | None = None,
    stake_units: Any | None = None,
    result: str | None = None,
    profit_units: Any | None = None,
    closing_odds: Any | None = None,
) -> dict[str, Any]:
    diagnostics = edge_report(model_probability, selection_odds, opposite_odds)
    close_clv_pp = None
    if closing_odds is not None:
        closing_implied = implied_probability(closing_odds)
        close_clv_pp = (closing_implied - diagnostics["market_implied_probability"]) * 100.0
    return {
        "schema": "v14-pick-audit-v1",
        "game_pk": str(game_pk),
        "market": str(market),
        "selection": str(selection),
        "model_version": str(model_version),
        "prediction_timestamp": prediction_timestamp or datetime.now(timezone.utc).isoformat(),
        **diagnostics,
        "stake_units": _num(stake_units),
        "result": result,
        "profit_units": _num(profit_units),
        "closing_odds": _num(closing_odds),
        "clv_implied_probability_pp": close_clv_pp,
    }


def append_tracking_record(
    record: dict[str, Any],
    path: Path | str = Path("data/v14_pick_audit.jsonl"),
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
