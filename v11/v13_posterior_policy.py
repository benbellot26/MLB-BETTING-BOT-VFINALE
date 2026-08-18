from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

POLICY_FILE = Path(os.getenv("V13_POSTERIOR_POLICY_FILE", "data/v13_posterior_policy.json"))
HISTORICAL_VALIDATION = Path(os.getenv("V13_HISTORICAL_VALIDATION_FILE", "data/v13_historical_validation.json"))
WEIGHT_GRID = tuple(i / 20 for i in range(21))  # 0%, 5%, ..., 100% Sharp
MIN_MARKET_GAMES = 50
MIN_PHASE_GAMES = 60
MIN_SELECTION_GAMES = 30
MIN_HOLDOUT = 20


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _game_key(row: dict[str, Any]) -> str:
    return str(row.get("game_pk") or "")


def _phase_rank(row: dict[str, Any]) -> tuple[int, str]:
    phase = str(row.get("phase") or "EARLY").upper()
    priority = {"EARLY": 0, "LATE": 1, "FINAL": 2}.get(phase, -1)
    return priority, str(row.get("observation_at") or row.get("analyzed_at") or row.get("game_date") or "")


def _valid(row: dict[str, Any]) -> bool:
    return (
        row.get("settled_result") in {"WIN", "LOSS"}
        and _num(row.get("p_baseball_calibrated")) is not None
        and _num(row.get("p_market")) is not None
        and bool(_game_key(row))
    )


def latest_phase_per_game(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one statistically independent forecast per game.

    Multiple EARLY/LATE/FINAL observations share the same final outcome and are
    therefore not allowed to inflate a pooled promotion sample size.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _valid(row):
            continue
        gid = _game_key(row)
        if gid not in best or _phase_rank(row) > _phase_rank(best[gid]):
            best[gid] = row
    return sorted(best.values(), key=lambda r: (str(r.get("game_date") or ""), _game_key(r)))


def one_per_game_phase(rows: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    phase = str(phase or "EARLY").upper()
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _valid(row) or str(row.get("phase") or "").upper() != phase:
            continue
        gid = _game_key(row)
        rank = str(row.get("observation_at") or row.get("analyzed_at") or row.get("game_date") or "")
        old = best.get(gid)
        old_rank = str((old or {}).get("observation_at") or (old or {}).get("analyzed_at") or (old or {}).get("game_date") or "")
        if old is None or rank > old_rank:
            best[gid] = row
    return sorted(best.values(), key=lambda r: (str(r.get("game_date") or ""), _game_key(r)))


def blend(baseball: float, market: float, weight: float) -> float:
    w = max(0.0, min(1.0, float(weight)))
    return max(.001, min(.999, (1.0 - w) * float(baseball) + w * float(market)))


def _metrics(rows: list[dict[str, Any]], weight: float) -> dict[str, Any]:
    vals = []
    for row in rows:
        if not _valid(row):
            continue
        b = float(row["p_baseball_calibrated"])
        m = float(row["p_market"])
        p = blend(b, m, weight)
        y = 1 if row["settled_result"] == "WIN" else 0
        ll = -(y * math.log(p) + (1 - y) * math.log(1 - p))
        vals.append((p, y, ll))
    if not vals:
        return {"n": 0, "brier": None, "logloss": None}
    return {
        "n": len(vals),
        "brier": sum((p - y) ** 2 for p, y, _ in vals) / len(vals),
        "logloss": sum(ll for _, _, ll in vals) / len(vals),
    }


def select_weight(rows: list[dict[str, Any]], minimum: int = MIN_SELECTION_GAMES) -> dict[str, Any]:
    """Select a Sharp blend weight using only rows already observed in the past."""
    clean = [r for r in rows if _valid(r)]
    games = len({_game_key(r) for r in clean})
    if games < minimum:
        return {"weight": 0.0, "games": games, "status": "COLLECTING", "grid": list(WEIGHT_GRID)}
    scored = []
    for weight in WEIGHT_GRID:
        metric = _metrics(clean, weight)
        # Prefer lower Brier, then lower LogLoss, then the smaller market weight.
        scored.append((float(metric["brier"]), float(metric["logloss"]), weight, metric))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    _, _, weight, metric = scored[0]
    return {
        "weight": weight,
        "games": games,
        "status": "LEARNED_FROM_PRIOR_GAMES",
        "metrics": metric,
        "grid": list(WEIGHT_GRID),
    }


def prior_only_weight(history: list[dict[str, Any]], market: str, phase: str) -> dict[str, Any]:
    """Weight for the next chronological validation block.

    Phase-specific evidence is preferred. If it is still too small, a pooled
    one-observation-per-game market history is used. No current/future block is
    ever consulted.
    """
    market = str(market or "").upper()
    phase = str(phase or "EARLY").upper()
    market_rows = [r for r in history if str(r.get("market") or "").upper() == market]
    phase_rows = one_per_game_phase(market_rows, phase)
    if len(phase_rows) >= MIN_SELECTION_GAMES:
        out = select_weight(phase_rows, MIN_SELECTION_GAMES)
        out["source"] = f"prior-only:{market}:{phase}"
        return out
    pooled = latest_phase_per_game(market_rows)
    out = select_weight(pooled, max(MIN_SELECTION_GAMES, 40))
    out["source"] = f"prior-only:{market}:POOLED" if out.get("status") != "COLLECTING" else "identity-insufficient-history"
    return out


def _fit_entry(rows: list[dict[str, Any]], minimum_games: int) -> dict[str, Any]:
    rows = sorted([r for r in rows if _valid(r)], key=lambda r: (str(r.get("game_date") or ""), _game_key(r)))
    n = len(rows)
    base = {
        "active_for_shadow": False,
        "weight": 0.0,
        "games": n,
        "minimum_games": minimum_games,
        "status": "COLLECTING",
        "weight_grid": list(WEIGHT_GRID),
    }
    if n < minimum_games or n < MIN_HOLDOUT + MIN_SELECTION_GAMES:
        return base
    hold_n = max(MIN_HOLDOUT, int(round(n * .20)))
    discovery, holdout = rows[:-hold_n], rows[-hold_n:]
    choice = select_weight(discovery, MIN_SELECTION_GAMES)
    weight = float(choice.get("weight") or 0.0)
    baseline = _metrics(holdout, 0.0)
    candidate = _metrics(holdout, weight)
    brier_gain = float(baseline["brier"]) - float(candidate["brier"])
    logloss_gain = float(baseline["logloss"]) - float(candidate["logloss"])
    passed = weight > 0 and brier_gain > 0 and logloss_gain > 0
    base.update({
        "active_for_shadow": passed,
        "weight": weight if passed else 0.0,
        "selected_weight": weight,
        "status": "SHADOW_VALIDATED" if passed else "BASEBALL_BEST_OR_UNSTABLE",
        "discovery_games": len(discovery),
        "holdout_games": len(holdout),
        "holdout_baseball": baseline,
        "holdout_candidate": candidate,
        "holdout_brier_gain": brier_gain,
        "holdout_logloss_gain": logloss_gain,
        "selection": choice,
    })
    return base


def build_policy(observations: list[dict[str, Any]]) -> dict[str, Any]:
    from .probability_contract_v13 import MODEL_GENERATION_FINGERPRINT

    entries: dict[str, Any] = {}
    for market in ("ML", "RUNLINE", "TOTAL"):
        market_rows = [r for r in observations if str(r.get("market") or "").upper() == market]
        entries[f"MARKET:{market}"] = _fit_entry(latest_phase_per_game(market_rows), MIN_MARKET_GAMES)
        for phase in ("EARLY", "LATE", "FINAL"):
            entries[f"PHASE:{phase}:{market}"] = _fit_entry(one_per_game_phase(market_rows, phase), MIN_PHASE_GAMES)
    return {
        "schema": "v13-posterior-weight-policy-v1",
        "model_generation": MODEL_GENERATION_FINGERPRINT,
        "primary_probability_affected": False,
        "promotion_requires_unique_games": True,
        "weight_selection": "chronological discovery + untouched holdout; 0..100% Sharp grid; phase preferred then market fallback",
        "entries": entries,
    }


def resolve_weight(policy: dict[str, Any], market: str, phase: str) -> tuple[float, str, int]:
    entries = policy.get("entries") or {}
    phase_key = f"PHASE:{str(phase or 'EARLY').upper()}:{str(market or '').upper()}"
    market_key = f"MARKET:{str(market or '').upper()}"
    for key in (phase_key, market_key):
        entry = entries.get(key) or {}
        if entry.get("active_for_shadow"):
            return max(0.0, min(1.0, float(entry.get("weight") or 0.0))), key, int(entry.get("games") or 0)
    return 0.0, "BASEBALL_ONLY_UNTIL_VALIDATED_WEIGHT", int((entries.get(phase_key) or {}).get("games") or 0)


def load_policy(path: Path = POLICY_FILE) -> dict[str, Any]:
    if not path.exists():
        return {"schema": "v13-posterior-weight-policy-v1", "entries": {}, "status": "ABSENT"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != "v13-posterior-weight-policy-v1":
            return {"schema": "v13-posterior-weight-policy-v1", "entries": {}, "status": "INCOMPATIBLE"}
        return data
    except Exception as exc:
        return {"schema": "v13-posterior-weight-policy-v1", "entries": {}, "status": "INVALID", "error": type(exc).__name__}


def _historical_observations(path: Path = HISTORICAL_VALIDATION) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [r for r in (data.get("observations") or []) if isinstance(r, dict)]


def _live_observations() -> list[dict[str, Any]]:
    try:
        from . import v13_daily_tracking as tracking
        states = list(tracking.fold().values())
    except Exception:
        return []
    out = []
    for row in states:
        if row.get("settled_result") not in {"WIN", "LOSS"}:
            continue
        if not row.get("predictive_final_status"):
            continue
        if _num(row.get("p_baseball_calibrated")) is None or _num(row.get("p_market")) is None:
            continue
        clone = dict(row)
        clone.setdefault("evidence_origin", "native-live-current-generation")
        out.append(clone)
    return out


def build_from_sources() -> dict[str, Any]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _historical_observations():
        key = (_game_key(row), str(row.get("phase") or "EARLY").upper(), str(row.get("market") or "").upper())
        merged[key] = row
    # Genuine current-generation live evidence wins collisions.
    for row in _live_observations():
        key = (_game_key(row), str(row.get("phase") or "EARLY").upper(), str(row.get("market") or "").upper())
        merged[key] = row
    policy = build_policy(list(merged.values()))
    policy["source_observations"] = len(merged)
    policy["historical_observations"] = sum(str(r.get("evidence_origin") or "").startswith("exact-replay") for r in merged.values())
    policy["live_observations"] = policy["source_observations"] - policy["historical_observations"]
    return policy


def save_policy(policy: dict[str, Any], path: Path = POLICY_FILE) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return policy


def main() -> None:
    policy = save_policy(build_from_sources())
    print(json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
