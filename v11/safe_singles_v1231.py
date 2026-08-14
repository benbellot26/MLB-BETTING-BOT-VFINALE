from __future__ import annotations

import os

_INSTALLED = False
_ORIGINAL_VALUE_GATE = None
_config = _selector = None


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def value_gate_with_single_price_floor(rec):
    """Keep the full model/value safety gate and add a hard execution-price floor.

    The 1.60 threshold is additive: it never relaxes EV, edge, uncertainty,
    data-quality, selection-score or Kelly requirements enforced downstream.
    """
    gate = dict(_ORIGINAL_VALUE_GATE(rec))
    price = _num(gate.get("price"), 0.0)
    floor = float(getattr(_config, "MIN_OFFICIAL_SINGLE_PRICE", 1.60))
    model_value_ok = bool(gate.get("ok"))
    price_floor_ok = bool(price + 1e-12 >= floor)
    gate.update({
        "model_value_ok": model_value_ok,
        "price_floor_ok": price_floor_ok,
        "min_official_single_price": floor,
        "ok": bool(model_value_ok and price_floor_ok),
    })
    return gate


def install():
    global _INSTALLED, _ORIGINAL_VALUE_GATE, _config, _selector
    if _INSTALLED:
        return True
    from . import config, selector
    _config, _selector = config, selector
    config.MIN_OFFICIAL_SINGLE_PRICE = float(
        os.getenv("V123_MIN_OFFICIAL_SINGLE_PRICE", "1.60") or 1.60
    )
    _ORIGINAL_VALUE_GATE = selector.value_gate
    selector.value_gate = value_gate_with_single_price_floor
    _INSTALLED = True
    return True


def installed():
    return _INSTALLED
