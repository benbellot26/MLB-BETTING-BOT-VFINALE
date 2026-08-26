from __future__ import annotations

"""Leakage-safe probability calibration for Pulsar V14.

Calibration is deliberately fail-closed. A calibrator only becomes active when
there is enough strictly-pregame, settled current-generation evidence AND an
untouched chronological holdout improves Brier score without worsening LogLoss.
Until that happens the identity transform is returned, so adding this module can
never silently rewrite production probabilities from a tiny sample.
"""

from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

PREDICTIONS = Path("data/v14_predictions.jsonl")
ARTIFACT = Path("data/v14_calibration.json")
MIN_MARKET_OBSERVATIONS = 400
MIN_PHASE_OBSERVATIONS = 300
MIN_HOLDOUT = 80
HOLDOUT_FRACTION = 0.20
L2 = 2.0
EPS = 1e-9

CANONICAL_MARKETS = {
    "ML": "home_ml",
    "RL_HOME_-1.5": "home_minus_1_5",
    "RL_AWAY_-1.5": "away_minus_1_5",
    "TOTAL_OVER": "over",
}
PAIR_MAP = {
    "home_ml": ("home_ml", "away_ml", "ML"),
    "home_minus_1_5": ("home_minus_1_5", "away_plus_1_5", "RL_HOME_-1.5"),
    "away_minus_1_5": ("away_minus_1_5", "home_plus_1_5", "RL_AWAY_-1.5"),
    "over": ("over", "under", "TOTAL_OVER"),
}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _clip(p: float) -> float:
    return min(1.0 - EPS, max(EPS, float(p)))


def _logit(p: float) -> float:
    q = _clip(p)
    return math.log(q / (1.0 - q))


def _sigmoid(z: float) -> float:
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _strictly_pregame(row: dict[str, Any]) -> bool:
    at = _parse_time(row.get("analyzed_at"))
    game = _parse_time(row.get("game_date"))
    return bool(at and game and at < game)


def _latest_settled_by_game(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("model_generation") != MODEL_GENERATION or not row.get("settled") or not _strictly_pregame(row):
            continue
        key = str(row.get("game_pk") or "")
        if not key:
            continue
        cur = latest.get(key)
        if cur is None or (_parse_time(row.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc)) > (_parse_time(cur.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc)):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: (str(r.get("target_date") or ""), str(r.get("game_pk") or "")))


def _outcome(row: dict[str, Any], market: str) -> int | None:
    hs = _num(row.get("home_score")); aws = _num(row.get("away_score"))
    if hs is None or aws is None:
        return None
    if market == "ML":
        return int(hs > aws)
    if market == "RL_HOME_-1.5":
        return int(hs - aws >= 2)
    if market == "RL_AWAY_-1.5":
        return int(aws - hs >= 2)
    if market == "TOTAL_OVER":
        line = _num(row.get("total_line"))
        return int(hs + aws > line) if line is not None else None
    return None


def observations(rows: list[dict[str, Any]]) -> dict[str, list[tuple[float, int, str]]]:
    out: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
    for row in _latest_settled_by_game(rows):
        probs = row.get("raw_probabilities") or row.get("probabilities") or {}
        phase = str(row.get("phase") or "EARLY").upper()
        for market, key in CANONICAL_MARKETS.items():
            p = _num(probs.get(key)); y = _outcome(row, market)
            if p is not None and y is not None and 0 < p < 1:
                out[market].append((float(p), int(y), phase))
    return dict(out)


def _scores(items: list[tuple[float, int]]) -> dict[str, float | int | None]:
    if not items:
        return {"n": 0, "brier": None, "log_loss": None, "mean_probability": None, "observed_rate": None, "ece": None}
    eps = 1e-12
    brier = sum((p - y) ** 2 for p, y in items) / len(items)
    ll = -sum(y * math.log(max(eps, min(1 - eps, p))) + (1 - y) * math.log(max(eps, min(1 - eps, 1 - p))) for p, y in items) / len(items)
    bins: list[list[tuple[float, int]]] = [[] for _ in range(10)]
    for p, y in items:
        bins[min(9, max(0, int(p * 10)))].append((p, y))
    ece = sum(len(v) / len(items) * abs(sum(p for p, _ in v) / len(v) - sum(y for _, y in v) / len(v)) for v in bins if v)
    return {"n": len(items), "brier": brier, "log_loss": ll, "mean_probability": sum(p for p, _ in items) / len(items), "observed_rate": sum(y for _, y in items) / len(items), "ece": ece}


def _fit_platt(items: list[tuple[float, int]]) -> tuple[float, float]:
    a, b = 1.0, 0.0
    for _ in range(60):
        gaa = gab = gbb = ga = gb = 0.0
        for p, y in items:
            x = _logit(p); q = _sigmoid(a * x + b); w = max(1e-8, q * (1 - q)); err = q - y
            ga += err * x; gb += err; gaa += w * x * x; gab += w * x; gbb += w
        ga += L2 * (a - 1.0); gb += L2 * b; gaa += L2; gbb += L2
        det = gaa * gbb - gab * gab
        if abs(det) < 1e-12:
            break
        da = (gbb * ga - gab * gb) / det; db = (-gab * ga + gaa * gb) / det
        scale = max(1.0, abs(da) / .25, abs(db) / .25)
        a -= da / scale; b -= db / scale
        if max(abs(da / scale), abs(db / scale)) < 1e-7:
            break
    return float(a), float(b)


def _fit_one(items: list[tuple[float, int]], *, minimum_n: int) -> dict[str, Any]:
    n = len(items); base = {"active": False, "method": "identity", "n": n, "minimum_n": minimum_n, "slope": 1.0, "intercept": 0.0}
    holdout_n = max(MIN_HOLDOUT, int(round(n * HOLDOUT_FRACTION))); train_n = n - holdout_n
    if n < minimum_n or train_n < 200 or holdout_n < MIN_HOLDOUT:
        return {**base, "status": "COLLECTING", "reason": "insufficient_chronological_evidence"}
    train, holdout = items[:train_n], items[train_n:]
    a, b = _fit_platt(train); raw = _scores(holdout); cal = _scores([(_sigmoid(a * _logit(p) + b), y) for p, y in holdout])
    brier_gain = float(raw["brier"] or 0) - float(cal["brier"] or 0); logloss_gain = float(raw["log_loss"] or 0) - float(cal["log_loss"] or 0)
    stable = 0.45 <= a <= 1.75 and abs(b) <= 1.25; active = bool(stable and brier_gain > 0.0 and logloss_gain >= -0.00025)
    return {**base, "active": active, "method": "platt-logit" if active else "identity", "status": "ACTIVE" if active else "REJECTED_OOS", "slope": a if active else 1.0, "intercept": b if active else 0.0, "candidate_slope": a, "candidate_intercept": b, "train_n": train_n, "holdout_n": holdout_n, "raw_holdout": raw, "calibrated_holdout": cal, "brier_gain": brier_gain, "logloss_gain": logloss_gain, "stable_parameters": stable, "reason": "strict_oos_gain" if active else "candidate_failed_strict_oos_gate"}


def build_artifact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    obs = observations(rows); calibrators: dict[str, Any] = {}
    for market in CANONICAL_MARKETS:
        market_obs = [(p, y) for p, y, _phase in obs.get(market, [])]; calibrators[f"MARKET:{market}"] = _fit_one(market_obs, minimum_n=MIN_MARKET_OBSERVATIONS)
        by_phase: dict[str, list[tuple[float, int]]] = defaultdict(list)
        for p, y, phase in obs.get(market, []): by_phase[phase].append((p, y))
        for phase in ("EARLY", "LATE", "FINAL"): calibrators[f"PHASE:{phase}:{market}"] = _fit_one(by_phase.get(phase, []), minimum_n=MIN_PHASE_OBSERVATIONS)
    return {"schema": "pulsar-v14-calibration-v1", "model_generation": MODEL_GENERATION, "generated_at": datetime.now(timezone.utc).isoformat(), "strictly_pregame": True, "chronological_holdout": True, "market_probability_used_as_feature": False, "calibrators": calibrators, "policy": {"market_min_n": MIN_MARKET_OBSERVATIONS, "phase_min_n": MIN_PHASE_OBSERVATIONS, "activation": "positive holdout Brier gain + non-worse LogLoss + stable Platt parameters"}}


def load_artifact(path: Path | str = ARTIFACT) -> dict[str, Any]:
    target = Path(path)
    if not target.exists(): return {"schema": "pulsar-v14-calibration-v1", "model_generation": MODEL_GENERATION, "calibrators": {}}
    try: payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception: return {"schema": "pulsar-v14-calibration-v1", "model_generation": MODEL_GENERATION, "calibrators": {}}
    if payload.get("schema") != "pulsar-v14-calibration-v1" or payload.get("model_generation") != MODEL_GENERATION: return {"schema": "pulsar-v14-calibration-v1", "model_generation": MODEL_GENERATION, "calibrators": {}}
    return payload


def _select_calibrator(artifact: dict[str, Any], market: str, phase: str) -> tuple[str, dict[str, Any]]:
    calibrators = artifact.get("calibrators") or {}; phase_key = f"PHASE:{str(phase).upper()}:{market}"; market_key = f"MARKET:{market}"
    phase_cal = calibrators.get(phase_key) or {}
    if phase_cal.get("active") is True: return phase_key, phase_cal
    market_cal = calibrators.get(market_key) or {}
    if market_cal.get("active") is True: return market_key, market_cal
    return market_key, market_cal or {"active": False, "method": "identity", "n": 0, "minimum_n": MIN_MARKET_OBSERVATIONS}


def calibrate_probability(p: float, market: str, phase: str, artifact: dict[str, Any] | None = None) -> tuple[float, dict[str, Any]]:
    data = load_artifact() if artifact is None else artifact; key, cal = _select_calibrator(data, market, phase); raw = _clip(p)
    if cal.get("active") is not True: return float(p), {"active": False, "key": key, "method": "identity", "n": int(cal.get("n") or 0), "status": str(cal.get("status") or "COLLECTING")}
    a = _num(cal.get("slope")); b = _num(cal.get("intercept"))
    if a is None or b is None: return float(p), {"active": False, "key": key, "method": "identity", "n": int(cal.get("n") or 0), "status": "INVALID_ARTIFACT"}
    return _sigmoid(a * _logit(raw) + b), {"active": True, "key": key, "method": "platt-logit", "n": int(cal.get("n") or 0), "slope": a, "intercept": b, "holdout": cal.get("calibrated_holdout") or {}}


def calibrate_surface(probabilities: dict[str, Any], *, phase: str, artifact: dict[str, Any] | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    surface = {k: float(v) for k, v in probabilities.items() if _num(v) is not None}; details: dict[str, Any] = {}
    for canonical_key, (left, right, market) in PAIR_MAP.items():
        if canonical_key not in surface or right not in surface: continue
        q, meta = calibrate_probability(surface[canonical_key], market, phase, artifact); q = min(1.0, max(0.0, q)); surface[left] = q; surface[right] = 1.0 - q; details[market] = meta
    return surface, {"schema": "pulsar-v14-calibration-application-v1", "phase": str(phase).upper(), "markets": details, "any_active": any(v.get("active") for v in details.values())}


def write_artifact(predictions: Path | str = PREDICTIONS, destination: Path | str = ARTIFACT) -> dict[str, Any]:
    artifact = build_artifact(_read_jsonl(predictions)); target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit leakage-safe Pulsar V14 probability calibrators"); parser.add_argument("command", choices=["fit"]); parser.add_argument("--predictions", default=str(PREDICTIONS)); parser.add_argument("--output", default=str(ARTIFACT)); args = parser.parse_args(); artifact = write_artifact(args.predictions, args.output); active = sum(bool(v.get("active")) for v in (artifact.get("calibrators") or {}).values()); print(f"PULSAR_V14_CALIBRATION active={active} output={args.output}")

if __name__ == "__main__": main()
