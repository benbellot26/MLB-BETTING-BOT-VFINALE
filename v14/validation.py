from __future__ import annotations

import math
from typing import Any

from .model import ProbabilitySurface


def _clip(p: float) -> float:
    return max(0.001, min(0.999, float(p)))


def brier(p: float, y: int) -> float:
    return (_clip(p) - int(y)) ** 2


def logloss(p: float, y: int) -> float:
    p = _clip(p)
    y = int(y)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def outcomes(home_score: int, away_score: int, total_line: float) -> dict[str, int]:
    hs, aps = int(home_score), int(away_score)
    if hs == aps:
        raise ValueError("settled MLB game cannot be tied")
    if abs(float(total_line) * 2 - round(float(total_line) * 2)) > 1e-9 or round(float(total_line) * 2) % 2 == 0:
        raise ValueError("validation requires the same half-run total line used by the forecast")
    diff = hs - aps
    total = hs + aps
    return {
        "home_ml": int(diff > 0),
        "home_minus_1_5": int(diff >= 2),
        "home_plus_1_5": int(diff >= -1),
        "over": int(total > float(total_line)),
    }


def score_surface(surface: ProbabilitySurface, *, home_score: int, away_score: int,
                  total_line: float) -> dict[str, Any]:
    """Score four statistically independent canonical binary targets.

    The eight displayed probabilities are four complementary pairs. Scoring both
    sides would duplicate the same outcome and artificially double sample size.
    """
    s = surface.validated()
    ys = outcomes(home_score, away_score, total_line)
    ps = {
        "home_ml": s.home_ml,
        "home_minus_1_5": s.home_minus_1_5,
        "home_plus_1_5": s.home_plus_1_5,
        "over": s.over,
    }
    by_target = {
        key: {"p": ps[key], "y": ys[key], "brier": brier(ps[key], ys[key]), "logloss": logloss(ps[key], ys[key])}
        for key in ps
    }
    return {
        "sample_policy": "four canonical complementary-pair targets; opposite sides never double-counted",
        "targets": by_target,
        "mean_brier": sum(v["brier"] for v in by_target.values()) / len(by_target),
        "mean_logloss": sum(v["logloss"] for v in by_target.values()) / len(by_target),
    }


def compare_to_champion(v14_surface: ProbabilitySurface, champion: dict[str, float], *,
                        home_score: int, away_score: int, total_line: float) -> dict[str, Any]:
    """Paired one-game comparison. Promotion decisions must aggregate chronologically."""
    v14_score = score_surface(v14_surface, home_score=home_score, away_score=away_score, total_line=total_line)
    champion_surface = ProbabilitySurface(**{k: float(champion[k]) for k in ProbabilitySurface.__dataclass_fields__}).validated()
    champ_score = score_surface(champion_surface, home_score=home_score, away_score=away_score, total_line=total_line)
    return {
        "v14": v14_score,
        "champion": champ_score,
        "brier_gain_vs_champion": champ_score["mean_brier"] - v14_score["mean_brier"],
        "logloss_gain_vs_champion": champ_score["mean_logloss"] - v14_score["mean_logloss"],
        "promotion_allowed": False,
        "reason": "single-game comparison is descriptive only; V14 promotion requires chronological aggregate evidence",
    }
