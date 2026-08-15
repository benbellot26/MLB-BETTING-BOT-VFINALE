from __future__ import annotations

from .methodology_v123 import install


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def selection_score_price_symmetric(rec, gate, dq):
    from . import config
    ev = max(-.20, min(.30, _num(gate.get("ev_at_price"), -.20)))
    price = _num(gate.get("price"), 0)
    push = max(0.0, min(.95, _num(gate.get("p_push"), 0)))
    pwin = max(0.0, min(1-push, _num(gate.get("p_win"), 0)))
    breakeven = (1-push)/price if price > 1 else 1.0
    # Relative edge is invariant to favorite/underdog price scale for equal EV.
    relative_edge = max(0.0, min(.30, pwin/max(1e-9, breakeven)-1.0)) if price > 1 else 0.0
    unc = max(0.0, _num(gate.get("uncertainty"), config.FALLBACK_MODEL_UNCERTAINTY))
    base = 45+155*max(0.0, ev)+35*relative_edge+18*(dq["score"]-.65)-80*unc

    # Sharp disagreement is a score penalty, not a direction veto. The model can
    # disagree with the market, but a large gap needs stronger EV/DQ to survive.
    sharp_gap = gate.get("sharp_disagreement")
    penalty = 0.0
    if sharp_gap is not None:
        free = max(0.0, _num(getattr(config, "V123_SHARP_GAP_FREE", .08), .08))
        scale = max(0.0, _num(getattr(config, "V123_SHARP_GAP_SCORE_PENALTY", 200.0), 200.0))
        penalty = min(12.0, scale*max(0.0, _num(sharp_gap)-free))
    return max(0.0, min(100.0, base-penalty))


def activate():
    install()
    from . import selector
    selector._score = selection_score_price_symmetric
    from .alternate_runlines_v1231 import install as install_alternate_runlines
    install_alternate_runlines()
    from .safe_singles_v1231 import install as install_value_selection
    install_value_selection()
    return True
