from __future__ import annotations

import math
from typing import Iterable

from .model import DEFAULT_MAX_RUNS, DEFAULT_TAIL_TOLERANCE, ProbabilitySurface, RunProjection


def negative_binomial_pmf(mu: float, dispersion: float, *, max_runs: int = DEFAULT_MAX_RUNS,
                          tail_tolerance: float = DEFAULT_TAIL_TOLERANCE) -> tuple[list[float], float]:
    """Return a normalized NB run PMF plus discarded tail mass.

    Parameterization: E[Y]=mu and Var[Y]=mu + mu^2/dispersion.
    A recurrence avoids repeated gamma evaluations and keeps the implementation
    dependency-free and auditable.
    """
    mu = float(mu)
    r = float(dispersion)
    if not math.isfinite(mu) or mu <= 0 or not math.isfinite(r) or r <= 0:
        raise ValueError("mu and dispersion must be finite and > 0")
    if max_runs < 10:
        raise ValueError("max_runs must be >= 10")
    if not 0 < tail_tolerance < 0.01:
        raise ValueError("tail_tolerance must be between 0 and 0.01")

    q = mu / (r + mu)
    p0 = (r / (r + mu)) ** r
    probs = [p0]
    cumulative = p0
    k = 0
    while k < max_runs and 1.0 - cumulative > tail_tolerance:
        next_p = probs[-1] * ((k + r) / (k + 1.0)) * q
        probs.append(next_p)
        cumulative += next_p
        k += 1

    if cumulative <= 0 or not math.isfinite(cumulative):
        raise ValueError("invalid negative-binomial mass")
    tail = max(0.0, 1.0 - cumulative)
    probs = [x / cumulative for x in probs]
    return probs, tail


def _joint(home_pmf: Iterable[float], away_pmf: Iterable[float]):
    hp = list(home_pmf)
    ap = list(away_pmf)
    for h, ph in enumerate(hp):
        if ph == 0:
            continue
        for a, pa in enumerate(ap):
            if pa:
                yield h, a, ph * pa


def probability_surface(projection: RunProjection, *, max_runs: int = DEFAULT_MAX_RUNS,
                        tail_tolerance: float = DEFAULT_TAIL_TOLERANCE) -> tuple[ProbabilitySurface, float]:
    """Generate the eight V14 probabilities from one coherent score distribution."""
    p = projection.validated()
    home_pmf, home_tail = negative_binomial_pmf(p.home_mu, p.dispersion, max_runs=max_runs,
                                                 tail_tolerance=tail_tolerance)
    away_pmf, away_tail = negative_binomial_pmf(p.away_mu, p.dispersion, max_runs=max_runs,
                                                 tail_tolerance=tail_tolerance)

    home_reg_win = away_reg_win = tie = 0.0
    home_minus = home_plus = 0.0
    over = 0.0

    for home_runs, away_runs, mass in _joint(home_pmf, away_pmf):
        diff = home_runs - away_runs
        total = home_runs + away_runs
        if diff > 0:
            home_reg_win += mass
        elif diff < 0:
            away_reg_win += mass
        else:
            tie += mass

        if diff >= 2:
            home_minus += mass
        if diff >= -1:
            home_plus += mass
        if total > p.total_line:
            over += mass

    # MLB has no regular-season draw. V14 foundation deliberately makes the
    # smallest possible extra-inning assumption: a tied regulation state is
    # split 50/50. This is explicit and can only be replaced after OOS proof.
    home_ml = home_reg_win + 0.5 * tie
    away_ml = 1.0 - home_ml
    home_minus = max(0.0, min(1.0, home_minus))
    home_plus = max(0.0, min(1.0, home_plus))
    over = max(0.0, min(1.0, over))

    surface = ProbabilitySurface(
        away_ml=away_ml,
        home_ml=home_ml,
        away_plus_1_5=1.0 - home_minus,
        away_minus_1_5=1.0 - home_plus,
        home_plus_1_5=home_plus,
        home_minus_1_5=home_minus,
        over=over,
        under=1.0 - over,
    ).validated()
    # Joint discarded mass is bounded by the union of marginal tails.
    tail_mass = min(1.0, home_tail + away_tail)
    return surface, tail_mass
