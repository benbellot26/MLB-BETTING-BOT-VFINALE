from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from . import MODEL_GENERATION, SCHEMA, VERSION


DEFAULT_DISPERSION = 7.5
DEFAULT_TAIL_TOLERANCE = 1e-8
DEFAULT_MAX_RUNS = 60


def _finite_positive(value: Any, name: str) -> float:
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"{name} must be finite and > 0")
    return out


def _half_run_line(value: Any) -> float:
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError("total_line must be numeric") from exc
    if not math.isfinite(out) or out <= 0:
        raise ValueError("total_line must be finite and > 0")
    doubled = round(out * 2)
    if abs(out * 2 - doubled) > 1e-9 or doubled % 2 == 0:
        raise ValueError("V14 display totals require a half-run line (e.g. 7.5, 8.5)")
    return out


@dataclass(frozen=True)
class RunProjection:
    game_pk: str
    game_date: str
    analyzed_at: str
    home: str
    away: str
    home_mu: float
    away_mu: float
    total_line: float
    phase: str = "FINAL"
    dispersion: float = DEFAULT_DISPERSION
    source_generation: str | None = None

    def validated(self) -> "RunProjection":
        if not str(self.game_pk):
            raise ValueError("game_pk is required")
        if not self.home or not self.away:
            raise ValueError("home and away are required")
        home_mu = _finite_positive(self.home_mu, "home_mu")
        away_mu = _finite_positive(self.away_mu, "away_mu")
        dispersion = _finite_positive(self.dispersion, "dispersion")
        total_line = _half_run_line(self.total_line)
        return RunProjection(
            game_pk=str(self.game_pk), game_date=str(self.game_date), analyzed_at=str(self.analyzed_at),
            home=str(self.home), away=str(self.away), home_mu=home_mu, away_mu=away_mu,
            total_line=total_line, phase=str(self.phase or "FINAL").upper(), dispersion=dispersion,
            source_generation=self.source_generation,
        )


@dataclass(frozen=True)
class ProbabilitySurface:
    away_ml: float
    home_ml: float
    away_plus_1_5: float
    away_minus_1_5: float
    home_plus_1_5: float
    home_minus_1_5: float
    over: float
    under: float

    def validated(self, tolerance: float = 1e-9) -> "ProbabilitySurface":
        values = asdict(self)
        for key, value in values.items():
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"invalid probability {key}={value}")
        pairs = (
            (self.away_ml, self.home_ml, "ML"),
            (self.away_plus_1_5, self.home_minus_1_5, "away+1.5/home-1.5"),
            (self.home_plus_1_5, self.away_minus_1_5, "home+1.5/away-1.5"),
            (self.over, self.under, "TOTAL"),
        )
        for left, right, label in pairs:
            if abs((left + right) - 1.0) > tolerance:
                raise ValueError(f"non-complementary V14 surface pair: {label}")
        return self

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def shadow_payload(projection: RunProjection, probabilities: ProbabilitySurface, *, tail_mass: float) -> dict[str, Any]:
    p = projection.validated()
    s = probabilities.validated()
    return {
        "schema": SCHEMA,
        "software_version": VERSION,
        "model_generation": MODEL_GENERATION,
        "role": "SHADOW_ONLY",
        "affects_production": False,
        "market_probability_used_as_feature": False,
        "game_pk": p.game_pk,
        "game_date": p.game_date,
        "analyzed_at": p.analyzed_at,
        "phase": p.phase,
        "home": p.home,
        "away": p.away,
        "source_generation": p.source_generation,
        "run_projection": {
            "home_mu": p.home_mu,
            "away_mu": p.away_mu,
            "dispersion": p.dispersion,
            "source": "explicit run projection input",
        },
        "total_line": p.total_line,
        "probabilities": s.as_dict(),
        "distribution": {
            "family": "independent-negative-binomial",
            "regulation_tie_resolution": "50/50 extra-inning neutral split",
            "tail_mass_truncated_before_renormalization": tail_mass,
        },
    }
