from __future__ import annotations

"""Deterministic paired/bootstrap inference for Pulsar research evidence.

This module is deliberately API-free. It operates only on already-persisted
observations and is suitable for certification/research reports where normal
approximations are too optimistic at small or moderately sized samples.
"""

from collections import defaultdict
from hashlib import sha256
import math
import random
from typing import Any, Iterable

DEFAULT_REPS = 5000


def _finite(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            x = float(value)
        except Exception:
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def _seed(label: str) -> int:
    return int.from_bytes(sha256(label.encode("utf-8")).digest()[:8], "big")


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = max(0.0, min(1.0, float(q))) * (len(sorted_values) - 1)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    weight = pos - lo
    return sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight


def bootstrap_mean_ci(values: Iterable[Any], *, reps: int = DEFAULT_REPS, label: str = "pulsar") -> dict[str, Any]:
    xs = _finite(values)
    n = len(xs)
    mean = sum(xs) / n if n else None
    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "ci95_lower": None,
            "ci95_upper": None,
            "method": "paired bootstrap mean; insufficient n" if n else "paired bootstrap mean",
            "reps": 0,
        }
    reps = max(500, int(reps))
    rng = random.Random(_seed(f"{label}|n={n}|reps={reps}"))
    samples: list[float] = []
    for _ in range(reps):
        samples.append(sum(xs[rng.randrange(n)] for _j in range(n)) / n)
    samples.sort()
    return {
        "n": n,
        "mean": mean,
        "ci95_lower": _percentile(samples, .025),
        "ci95_upper": _percentile(samples, .975),
        "method": "paired nonparametric bootstrap mean",
        "reps": reps,
        "deterministic_seed": True,
    }


def block_bootstrap_mean_ci(
    observations: Iterable[tuple[str, Any]],
    *,
    reps: int = DEFAULT_REPS,
    label: str = "pulsar-block",
) -> dict[str, Any]:
    """Bootstrap calendar blocks (normally game dates) instead of observations.

    This is a conservative companion diagnostic for temporal dependence. Each
    sampled block contributes all observations from that day.
    """
    grouped: dict[str, list[float]] = defaultdict(list)
    for block, value in observations:
        vals = _finite([value])
        if vals:
            grouped[str(block)].append(vals[0])
    blocks = sorted(grouped)
    n = sum(len(grouped[b]) for b in blocks)
    flat = [x for b in blocks for x in grouped[b]]
    mean = sum(flat) / len(flat) if flat else None
    if len(blocks) < 2 or n < 2:
        return {
            "n": n,
            "blocks": len(blocks),
            "mean": mean,
            "ci95_lower": None,
            "ci95_upper": None,
            "method": "calendar-block bootstrap; insufficient blocks",
            "reps": 0,
        }
    reps = max(500, int(reps))
    rng = random.Random(_seed(f"{label}|blocks={len(blocks)}|n={n}|reps={reps}"))
    samples: list[float] = []
    for _ in range(reps):
        draw: list[float] = []
        for _j in range(len(blocks)):
            draw.extend(grouped[blocks[rng.randrange(len(blocks))]])
        samples.append(sum(draw) / len(draw))
    samples.sort()
    return {
        "n": n,
        "blocks": len(blocks),
        "mean": mean,
        "ci95_lower": _percentile(samples, .025),
        "ci95_upper": _percentile(samples, .975),
        "method": "calendar-block nonparametric bootstrap mean",
        "reps": reps,
        "deterministic_seed": True,
    }


def paired_score_differences(items: Iterable[tuple[float, float, int]]) -> dict[str, list[float]]:
    """Return sharp-minus-model proper-score differences; positive favors model."""
    brier: list[float] = []
    logloss: list[float] = []
    eps = 1e-12
    for model_p, sharp_p, y in items:
        m = max(eps, min(1.0 - eps, float(model_p)))
        s = max(eps, min(1.0 - eps, float(sharp_p)))
        z = int(y)
        brier.append((s - z) ** 2 - (m - z) ** 2)
        mll = -(z * math.log(m) + (1 - z) * math.log(1 - m))
        sll = -(z * math.log(s) + (1 - z) * math.log(1 - s))
        logloss.append(sll - mll)
    return {"brier_gain": brier, "logloss_gain": logloss}
