from __future__ import annotations

import math
from typing import Any

from .model import ProbabilitySurface

# Frozen comparison target. This is benchmark metadata only and is never a V14
# model input. A future V13 generation requires an explicit benchmark reset.
CHAMPION_GENERATION = "v13.10-gen-structural-nb-independent-transfer-park-extra-surface-v3"


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _prob(option: dict[str, Any]) -> float | None:
    value = option.get("p_predictive_final")
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) and 0.0 <= out <= 1.0 else None


def _find(options: list[dict[str, Any]], market: str, name: str, point: float | None = None) -> dict[str, Any] | None:
    target_name = _norm(name)
    for option in options:
        if str(option.get("market") or "").upper() != market:
            continue
        if _norm(option.get("name")) != target_name:
            continue
        if point is not None:
            try:
                if abs(float(option.get("point")) - point) > 1e-9:
                    continue
            except Exception:
                continue
        return option
    return None


def champion_surface(result: dict[str, Any], *, total_line: float) -> ProbabilitySurface:
    """Extract the frozen V13.10 display surface for paired evaluation only."""
    generation = result.get("model_generation")
    if generation != CHAMPION_GENERATION:
        raise ValueError(f"benchmark generation mismatch: {generation}")
    home = str((result.get("ctx") or {}).get("home") or result.get("home") or "")
    away = str((result.get("ctx") or {}).get("away") or result.get("away") or "")
    options = [o for o in (result.get("options") or []) if isinstance(o, dict)]
    required = {
        "away_ml": _find(options, "ML", away),
        "home_ml": _find(options, "ML", home),
        "away_plus_1_5": _find(options, "RUNLINE", away, 1.5),
        "away_minus_1_5": _find(options, "RUNLINE", away, -1.5),
        "home_plus_1_5": _find(options, "RUNLINE", home, 1.5),
        "home_minus_1_5": _find(options, "RUNLINE", home, -1.5),
        "over": _find(options, "TOTAL", "Over", float(total_line)),
        "under": _find(options, "TOTAL", "Under", float(total_line)),
    }
    missing = [key for key, option in required.items() if option is None or _prob(option) is None]
    if missing:
        raise ValueError(f"incomplete champion probability surface: {missing}")
    return ProbabilitySurface(**{key: float(_prob(option)) for key, option in required.items()}).validated(tolerance=2e-6)


def benchmark_payload(result: dict[str, Any], *, total_line: float) -> dict[str, Any]:
    surface = champion_surface(result, total_line=total_line)
    return {
        "role": "FROZEN_CHAMPION_BENCHMARK_ONLY",
        "model_generation": CHAMPION_GENERATION,
        "used_as_v14_model_input": False,
        "probabilities": surface.as_dict(),
    }
