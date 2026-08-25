from __future__ import annotations

import math

from .champion_contract import MAX_RUNS_HARD, MAX_RUNS_MATRIX, SCORE_TAIL_TOLERANCE
from .model import DEFAULT_MAX_RUNS, DEFAULT_TAIL_TOLERANCE, ProbabilitySurface, RunProjection


def _nb_mass(mu: float, runs: int, dispersion: float) -> float:
    r = max(0.5, float(dispersion))
    mean = max(0.01, float(mu))
    p = r / (r + mean)
    return math.exp(
        math.lgamma(runs + r) - math.lgamma(r) - math.lgamma(runs + 1)
        + r * math.log(p) + runs * math.log1p(-p)
    )


def negative_binomial_pmf(mu: float, dispersion: float, *, max_runs: int = DEFAULT_MAX_RUNS,
                          tail_tolerance: float = DEFAULT_TAIL_TOLERANCE) -> tuple[list[float], float]:
    """Standalone normalized NB PMF used by diagnostics/tests.

    The champion score matrix below deliberately follows the V13.10 truncation
    and common-environment-mixture algorithm exactly. This helper remains useful
    for validating the underlying NB parameterization and mean.
    """
    mu = float(mu)
    dispersion = float(dispersion)
    if not math.isfinite(mu) or mu <= 0 or not math.isfinite(dispersion) or dispersion <= 0:
        raise ValueError("mu and dispersion must be finite and > 0")
    if max_runs < 10:
        raise ValueError("max_runs must be >= 10")
    if not 0 < tail_tolerance < 0.01:
        raise ValueError("tail_tolerance must be between 0 and 0.01")
    probs = []
    cumulative = 0.0
    for runs in range(max_runs + 1):
        value = _nb_mass(mu, runs, dispersion)
        probs.append(value)
        cumulative += value
        if runs >= 10 and 1.0 - cumulative <= tail_tolerance:
            break
    tail = max(0.0, 1.0 - cumulative)
    probs = [value / max(1e-15, cumulative) for value in probs]
    return probs, tail


def _required_max_runs(mu: float, dispersion: float, minimum: int | None = None) -> int:
    minimum = int(minimum or MAX_RUNS_MATRIX)
    cumulative = 0.0
    for runs in range(MAX_RUNS_HARD + 1):
        cumulative += _nb_mass(mu, runs, dispersion)
        if runs >= minimum and 1.0 - cumulative <= SCORE_TAIL_TOLERANCE:
            return runs
    return MAX_RUNS_HARD


def _environment_nodes(sigma: float) -> list[tuple[float, float]]:
    sigma = max(0.0, min(0.30, float(sigma)))
    if sigma <= 1e-9:
        return [(1.0, 1.0)]
    delta = math.sqrt(3.0) * sigma
    return [(max(0.45, 1.0 - delta), 1.0 / 6.0), (1.0, 2.0 / 3.0), (1.0 + delta, 1.0 / 6.0)]


def joint_score_matrix(home_mu: float, away_mu: float, *, dispersion: float,
                       environment_sigma: float, minimum_runs: int | None = None) -> tuple[list[list[float]], float]:
    """Clean port of the V13.10 champion correlated NB environment mixture."""
    nodes = _environment_nodes(environment_sigma)
    max_factor = max(factor for factor, _weight in nodes)
    max_runs = max(
        _required_max_runs(home_mu * max_factor, dispersion, minimum_runs),
        _required_max_runs(away_mu * max_factor, dispersion, minimum_runs),
    )
    joint = [[0.0] * (max_runs + 1) for _ in range(max_runs + 1)]
    estimated_tail = 0.0
    for factor, weight in nodes:
        home_raw = [_nb_mass(home_mu * factor, runs, dispersion) for runs in range(max_runs + 1)]
        away_raw = [_nb_mass(away_mu * factor, runs, dispersion) for runs in range(max_runs + 1)]
        home_sum = sum(home_raw)
        away_sum = sum(away_raw)
        home = [value / max(1e-15, home_sum) for value in home_raw]
        away = [value / max(1e-15, away_sum) for value in away_raw]
        estimated_tail += weight * min(1.0, max(0.0, (1.0 - home_sum) + (1.0 - away_sum)))
        for h, home_probability in enumerate(home):
            for a, away_probability in enumerate(away):
                joint[h][a] += weight * home_probability * away_probability
    total = sum(sum(row) for row in joint)
    normalized = [[value / max(1e-15, total) for value in row] for row in joint]
    return normalized, max(0.0, min(1.0, estimated_tail))


def probability_surface(projection: RunProjection, *, max_runs: int | None = None,
                        tail_tolerance: float | None = None) -> tuple[ProbabilitySurface, float]:
    """Generate the eight V14 probabilities with V13.10 champion parity math.

    `max_runs` and `tail_tolerance` remain accepted for API compatibility, but
    champion parity uses the frozen V13.10 dynamic truncation contract instead
    of the earlier V14 independent-NB foundation behavior.
    """
    del tail_tolerance
    p = projection.validated()
    joint, tail_mass = joint_score_matrix(
        p.home_mu,
        p.away_mu,
        dispersion=p.dispersion,
        environment_sigma=p.environment_sigma,
        minimum_runs=max_runs,
    )

    home_reg_win = tie = 0.0
    home_minus = home_plus = 0.0
    over = 0.0
    for home_runs, row in enumerate(joint):
        for away_runs, mass in enumerate(row):
            difference = home_runs - away_runs
            total = home_runs + away_runs
            if difference > 0:
                home_reg_win += mass
            elif difference == 0:
                tie += mass
            if difference >= 2:
                home_minus += mass
            if difference >= -1:
                home_plus += mass
            if total > p.total_line:
                over += mass

    home_ml = home_reg_win + tie * p.extra_innings_home_probability
    home_ml = max(0.0, min(1.0, home_ml))
    home_minus = max(0.0, min(1.0, home_minus))
    home_plus = max(0.0, min(1.0, home_plus))
    over = max(0.0, min(1.0, over))

    return ProbabilitySurface(
        away_ml=1.0 - home_ml,
        home_ml=home_ml,
        away_plus_1_5=1.0 - home_minus,
        away_minus_1_5=1.0 - home_plus,
        home_plus_1_5=home_plus,
        home_minus_1_5=home_minus,
        over=over,
        under=1.0 - over,
    ).validated(), tail_mass
