from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from . import park


@dataclass(frozen=True)
class StructuralRunInput:
    game_pk: str
    game_date: str
    venue: str
    structural_home_mu: float
    structural_away_mu: float
    static_park_factor: float

    def validated(self) -> "StructuralRunInput":
        for name, value in (
            ("structural_home_mu", self.structural_home_mu),
            ("structural_away_mu", self.structural_away_mu),
            ("static_park_factor", self.static_park_factor),
        ):
            try:
                number = float(value)
            except Exception as exc:
                raise ValueError(f"{name} must be numeric") from exc
            if not math.isfinite(number) or number <= 0:
                raise ValueError(f"{name} must be finite and > 0")
        if not str(self.game_pk):
            raise ValueError("game_pk is required")
        if not str(self.game_date):
            raise ValueError("game_date is required")
        return StructuralRunInput(
            game_pk=str(self.game_pk),
            game_date=str(self.game_date),
            venue=str(self.venue or ""),
            structural_home_mu=float(self.structural_home_mu),
            structural_away_mu=float(self.structural_away_mu),
            static_park_factor=float(self.static_park_factor),
        )


def _num(value: Any) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _season(game_date: str) -> int:
    try:
        return datetime.fromisoformat(str(game_date).replace("Z", "+00:00")).year
    except Exception as exc:
        raise ValueError("invalid game_date") from exc


def _inactive_legacy_guards(result: dict[str, Any]) -> list[str]:
    """Return active legacy run layers not yet needed by the frozen champion port.

    V14 fails closed rather than silently dropping a layer if V13.10 later
    activates one while parity migration is in progress.
    """
    features = result.get("features") or {}
    blockers: list[str] = []
    bootstrap = features.get("historical_bootstrap") or {}
    run_prior = bootstrap.get("run_prior") or {}
    if bool(run_prior.get("active")):
        blockers.append("V12_3_HISTORICAL_RUN_PRIOR_ACTIVE")
    v13_mean = bootstrap.get("v13_run_mean_prior") or {}
    if bool(v13_mean.get("active")):
        blockers.append("V13_RUN_MEAN_PRIOR_ACTIVE")
    learned = features.get("learned_run_adjustment") or {}
    if bool(learned.get("active")):
        blockers.append("V13_CHAMPION_RESIDUAL_ACTIVE")
    return blockers


def input_from_champion_result(result: dict[str, Any]) -> StructuralRunInput:
    """Extract the pre-V13-run-stack structural baseline from a V13.10 snapshot."""
    features = result.get("features") or {}
    game = result.get("game") or {}
    park_meta = features.get("park_factor_runtime") or {}

    # `features.structural_*` are produced by the V12.3 structural engine before
    # V13's prior-season park replacement. Root `structural_hmu/amu` are mutated
    # by V13 after park application and therefore are intentionally not preferred.
    home_mu = _num(features.get("structural_home_mu"))
    away_mu = _num(features.get("structural_away_mu"))
    if home_mu is None or away_mu is None:
        raise ValueError("snapshot missing pre-park V12.3 structural run means")

    static_factor = _num(park_meta.get("static_factor"))
    if static_factor is None:
        raise ValueError("snapshot missing static park factor required for parity")
    venue = str(((game.get("venue") or {}).get("name")) or park_meta.get("venue") or "")
    game_date = result.get("game_date") or game.get("gameDate")
    if not game_date:
        raise ValueError("snapshot missing game_date")
    return StructuralRunInput(
        game_pk=str(result.get("game_pk") or game.get("gamePk") or ""),
        game_date=str(game_date),
        venue=venue,
        structural_home_mu=home_mu,
        structural_away_mu=away_mu,
        static_park_factor=static_factor,
    ).validated()


def apply_current_champion(structural: StructuralRunInput, *, park_artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Native V14 run-stack port for the currently active V13.10 components.

    At the frozen champion state, V12.3 historical run priors, V13 historical
    run-mean transfer and the learned champion residual are inactive. Therefore
    the active V13.10 run-stack transformation after the V12.3 structural base is
    the validated prior-season park replacement. Inactive candidates are not
    copied into the baseline.
    """
    s = structural.validated()
    home_mu, away_mu, park_meta = park.apply(
        s.structural_home_mu,
        s.structural_away_mu,
        target_season=_season(s.game_date),
        venue=s.venue,
        static_factor=s.static_park_factor,
        artifact=park_artifact,
    )
    return {
        "home_mu": home_mu,
        "away_mu": away_mu,
        "structural_home_mu": s.structural_home_mu,
        "structural_away_mu": s.structural_away_mu,
        "park": park_meta,
        "active_layers": ["V12_3_STRUCTURAL_BASE", "PRIOR_SEASON_PARK_FACTOR" if park_meta.get("active") else "STATIC_PARK_FALLBACK"],
        "excluded_inactive_candidates": [
            "V12_3_HISTORICAL_RUN_PRIOR",
            "V13_RUN_MEAN_PRIOR",
            "V13_CHAMPION_RESIDUAL",
        ],
    }


def reproduce_from_champion_result(result: dict[str, Any]) -> dict[str, Any]:
    blockers = _inactive_legacy_guards(result)
    if blockers:
        raise ValueError("V14 run-stack parity missing newly active champion layer(s): " + ",".join(blockers))
    return apply_current_champion(input_from_champion_result(result))
