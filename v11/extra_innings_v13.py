from __future__ import annotations

import math
from typing import Any


def _num(x: Any, d: float = 0.0) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def regulation_home_win_probability(joint: list[list[float]]) -> tuple[float,float]:
    win = tie = 0.0
    for h,row in enumerate(joint):
        for a,p in enumerate(row):
            if h > a:
                win += p
            elif h == a:
                tie += p
    return win,tie


def home_win_probability(joint: list[list[float]], extra_innings_home_prior: float | None = None) -> float:
    """Use a neutral extra-innings prior unless a separately validated prior exists.

    The previous fixed .52 tie split is retained only as an optional externally
    supplied validated prior. The default is intentionally 50/50.
    """
    win,tie = regulation_home_win_probability(joint)
    prior = .5 if extra_innings_home_prior is None else max(.45,min(.55,_num(extra_innings_home_prior,.5)))
    return max(.001,min(.999,win+tie*prior))
