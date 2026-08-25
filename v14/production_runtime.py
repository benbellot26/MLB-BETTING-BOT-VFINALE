from __future__ import annotations

"""Production runtime boundary for Pulsar V14.

The legacy V13 runner is temporarily tolerated as an acquisition adapter only.
This module owns the V14 prediction payload and Discord publication boundary so
legacy probabilities cannot leak into user-facing V14 cards.
"""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, VERSION
from .feature_row import load_latest_feature_row
from .pipeline import predict_from_result

LEGACY_PAYLOAD = Path("runtime/v11/discord_payload.json")
V14_PAYLOAD = Path("runtime/v14/discord_payload.json")
FEATURE_STORE = Path("data/v13_feature_store.jsonl")


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _point(option: dict[str, Any]) -> float | None:
    try:
        value = float(option.get("point"))
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _is_half_run(value: Any) -> bool:
    try:
        x = float(value)
    except Exception:
        return False
    doubled = round(x * 2)
    return math.isfinite(x) and x > 0 and abs(x * 2 - doubled) <= 1e-9 and doubled % 2 == 1


def _total_pairs(result: dict[str, Any]) -> dict[float, dict[str, dict[str, Any]]]:
    pairs: dict[float, dict[str, dict[str, Any]]] = {}
    for option in result.get("options") or []:
        if str(option.get("market") or "").upper() != "TOTAL":
            continue
        point = _point(option)
        side = str(option.get("name") or "").lower()
        if point is None or side not in {"over", "under"}:
            continue
        pairs.setdefault(point, {})[side] = option
    return {point: sides for point, sides in pairs.items() if {"over", "under"} <= set(sides)}


def choose_total_line(result: dict[str, Any]) -> float:
    pairs = _total_pairs(result)
    canonical = (result.get("canonical_lines") or {}).get("TOTAL")
    if canonical is not None:
        try:
            target = float(canonical)
        except Exception:
            target = None
        if target is not None and target in pairs and _is_half_run(target):
            return target

    eligible = sorted(point for point in pairs if _is_half_run(point))
    if not eligible:
        raise ValueError("no complete half-run TOTAL pair available for V14")
    if canonical is None:
        return eligible[len(eligible) // 2]
    try:
        target = float(canonical)
    except Exception:
        target = eligible[len(eligible) // 2]
    return min(eligible, key=lambda point: (abs(point - target), point))


def _write_probability(option: dict[str, Any], probability: float) -> None:
    p = float(probability)
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise ValueError("invalid V14 probability")
    rounded = round(p, 8)
    option["p_baseball_calibrated"] = rounded
    option["p_predictive_final"] = rounded
    option["p_effective"] = rounded
    option["p_win"] = rounded
    option["p_push"] = 0.0
    option["p_push_model"] = 0.0
    option["calibration_source"] = "PULSAR_V14_NATIVE"
    option["model_generation"] = MODEL_GENERATION
    option["market_probability_used_as_feature"] = False


def _find_team_option(result: dict[str, Any], market: str, team: str, point: float | None = None) -> dict[str, Any]:
    for option in result.get("options") or []:
        if str(option.get("market") or "").upper() != market:
            continue
        if _norm(option.get("name")) != _norm(team):
            continue
        if point is not None:
            option_point = _point(option)
            if option_point is None or abs(option_point - point) > 1e-6:
                continue
        return option
    raise ValueError(f"missing {market} option for {team} point={point}")


def _find_total_option(result: dict[str, Any], side: str, point: float) -> dict[str, Any]:
    for option in result.get("options") or []:
        if str(option.get("market") or "").upper() != "TOTAL":
            continue
        if str(option.get("name") or "").lower() != side:
            continue
        option_point = _point(option)
        if option_point is not None and abs(option_point - point) <= 1e-6:
            return option
    raise ValueError(f"missing TOTAL {side} {point}")


def promote_result(result: dict[str, Any], *, feature_store: Path | str = FEATURE_STORE) -> dict[str, Any]:
    out = deepcopy(result)
    game_pk = out.get("game_pk") or (out.get("game") or {}).get("gamePk")
    analyzed_at = out.get("analyzed_at") or out.get("as_of")
    total_line = choose_total_line(out)
    feature_row = load_latest_feature_row(feature_store, game_pk=game_pk, as_of=analyzed_at)
    prediction = predict_from_result(out, total_line=total_line, feature_row=feature_row)
    probabilities = prediction["probabilities"]
    ctx = out.get("ctx") or {}
    home, away = str(ctx.get("home") or prediction.get("home")), str(ctx.get("away") or prediction.get("away"))

    _write_probability(_find_team_option(out, "ML", away), probabilities["away_ml"])
    _write_probability(_find_team_option(out, "ML", home), probabilities["home_ml"])
    _write_probability(_find_team_option(out, "RUNLINE", away, +1.5), probabilities["away_plus_1_5"])
    _write_probability(_find_team_option(out, "RUNLINE", away, -1.5), probabilities["away_minus_1_5"])
    _write_probability(_find_team_option(out, "RUNLINE", home, +1.5), probabilities["home_plus_1_5"])
    _write_probability(_find_team_option(out, "RUNLINE", home, -1.5), probabilities["home_minus_1_5"])
    _write_probability(_find_total_option(out, "over", total_line), probabilities["over"])
    _write_probability(_find_total_option(out, "under", total_line), probabilities["under"])

    out.setdefault("canonical_lines", {})["TOTAL"] = total_line
    out["hmu"] = prediction["run_projection"]["home_mu"]
    out["amu"] = prediction["run_projection"]["away_mu"]
    out["p_home"] = probabilities["home_ml"]
    out["model_generation"] = MODEL_GENERATION
    out["v14_prediction"] = prediction
    out["v14_feature_row_used"] = feature_row is not None
    out["market_probability_used_as_feature"] = False
    model = dict(out.get("model") or {})
    model.update({"version": VERSION, "generation": MODEL_GENERATION, "role": "PRODUCTION"})
    out["model"] = model
    return out


def promote_payload(payload: dict[str, Any], *, feature_store: Path | str = FEATURE_STORE) -> dict[str, Any]:
    results = [promote_result(result, feature_store=feature_store) for result in payload.get("results") or []]
    report = deepcopy(payload.get("report") or {})
    report["version"] = VERSION
    report["model_generation"] = MODEL_GENERATION
    report["production"] = {
        "engine": "PULSAR_V14",
        "role": "PRODUCTION",
        "legacy_acquisition_adapter": True,
        "legacy_probability_used_for_publication": False,
    }
    return {
        "schema": "pulsar-v14-discord-payload-v1",
        "version": VERSION,
        "model_generation": MODEL_GENERATION,
        "role": "PRODUCTION",
        "legacy_acquisition_adapter": True,
        "legacy_probability_used_for_publication": False,
        "results": results,
        "portfolio": {},
        "chosen": [],
        "combo": {},
        "health": deepcopy(payload.get("health") or {}),
        "report": report,
    }


def build_persisted(*, source: Path | str = LEGACY_PAYLOAD, destination: Path | str = V14_PAYLOAD, feature_store: Path | str = FEATURE_STORE) -> dict[str, Any]:
    source, destination = Path(source), Path(destination)
    if not source.exists():
        raise SystemExit(f"legacy acquisition payload absent: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    promoted = promote_payload(payload, feature_store=feature_store)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(promoted, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"PULSAR_V14_PAYLOAD games={len(promoted['results'])} path={destination}")
    return promoted


def send_persisted(*, path: Path | str = V14_PAYLOAD) -> None:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"V14 Discord payload absent: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("model_generation") != MODEL_GENERATION or payload.get("role") != "PRODUCTION":
        raise SystemExit("invalid V14 production payload")

    # Renderer is intentionally still reused while Discord I/O is migrated.
    # It receives only V14-overwritten probabilities from this payload.
    from v11 import core, discord_v13

    discord_v13.VERSION_LABEL = "PULSAR V14"
    try:
        discord_v13.base.VERSION_LABEL = "PULSAR V14"
    except Exception:
        pass
    if not core.discord_test():
        raise SystemExit("Discord webhook unavailable")
    ok = True
    for result in payload.get("results") or []:
        ok = bool(discord_v13.send_game(result, {})) and ok
    if not ok:
        raise SystemExit("Pulsar V14 Discord publication incomplete")
    print(f"PULSAR_V14_DISCORD published_games={len(payload.get('results') or [])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pulsar V14 production runtime boundary")
    parser.add_argument("--send-persisted", action="store_true")
    parser.add_argument("--source", default=str(LEGACY_PAYLOAD))
    parser.add_argument("--destination", default=str(V14_PAYLOAD))
    parser.add_argument("--feature-store", default=str(FEATURE_STORE))
    args = parser.parse_args()
    if args.send_persisted:
        send_persisted(path=args.destination)
    else:
        build_persisted(source=args.source, destination=args.destination, feature_store=args.feature_store)


if __name__ == "__main__":
    main()
