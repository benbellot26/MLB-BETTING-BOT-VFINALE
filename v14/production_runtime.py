from __future__ import annotations

"""Native production runtime for Pulsar V14.

The production path is now V14 end-to-end: native MLB/Odds acquisition, native
structural inputs, V14 prediction, native payload, native Discord publication.
No V11/V13 runtime or probability payload is accepted here.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION
from .acquisition import resolve_target_date
from .discord import send_game
from .native_candidate import build_candidate, persist_candidate
from .native_payload import authorize_payload, build_native_discord_payload

V14_CANDIDATE = Path("runtime/v14/native_candidate.json")
V14_PAYLOAD = Path("runtime/v14/discord_payload.json")

# Explicit human-approved cutover evidence. This is deliberately static and
# auditable rather than an automatic parity self-promotion mechanism.
NATIVE_CUTOVER_EVIDENCE = {
    "workflow": "Pulsar V14 Native Parity",
    "run_id": 32828843533,
    "comparable_games": 15,
    "candidate_coverage": 1.0,
    "mean_abs_structural_run_delta": 0.0,
    "max_abs_structural_run_delta": 0.0,
    "status": "PASS",
}


def _required_float(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if value is None:
        raise RuntimeError(f"native cutover evidence missing {key}")
    return float(value)


def _validate_cutover_evidence() -> None:
    evidence = NATIVE_CUTOVER_EVIDENCE
    if evidence.get("status") != "PASS":
        raise RuntimeError("native cutover evidence is not PASS")
    if int(evidence.get("comparable_games") or 0) < 8:
        raise RuntimeError("native cutover evidence has insufficient games")
    if _required_float(evidence, "candidate_coverage") < 0.90:
        raise RuntimeError("native cutover evidence has insufficient coverage")
    if _required_float(evidence, "mean_abs_structural_run_delta") > 0.03:
        raise RuntimeError("native cutover mean structural delta too large")
    if _required_float(evidence, "max_abs_structural_run_delta") > 0.10:
        raise RuntimeError("native cutover max structural delta too large")


def validate_production_payload(payload: dict[str, Any]) -> None:
    if payload.get("role") != "PRODUCTION":
        raise ValueError("V14 payload is not production")
    if payload.get("publication_authorized") is not True:
        raise ValueError("V14 payload publication is not authorized")
    if payload.get("model_generation") != MODEL_GENERATION:
        raise ValueError("V14 payload generation mismatch")
    if payload.get("native_acquisition") is not True:
        raise ValueError("V14 payload is not native acquisition")
    if payload.get("legacy_acquisition_adapter") is not False:
        raise ValueError("legacy acquisition leaked into V14 production")
    if payload.get("legacy_probability_used_for_publication") is not False:
        raise ValueError("legacy probability publication leak")
    if payload.get("market_probability_used_as_feature") is not False:
        raise ValueError("market probability feature leak")
    if payload.get("chosen"):
        raise ValueError("analytics payload contains recommendations")
    if (payload.get("combo") or {}).get("official"):
        raise ValueError("analytics payload contains official combo")

    for result in payload.get("results") or []:
        if result.get("model_generation") != MODEL_GENERATION:
            raise ValueError(f"game {result.get('game_pk')} is not V14")
        if result.get("native_acquisition") is not True:
            raise ValueError(f"game {result.get('game_pk')} is not native acquisition")
        prediction = result.get("v14_prediction") or {}
        if prediction.get("model_generation") != MODEL_GENERATION or prediction.get("role") != "PRODUCTION":
            raise ValueError(f"game {result.get('game_pk')} missing V14 production prediction")
        if prediction.get("market_probability_used_as_feature") is not False:
            raise ValueError(f"game {result.get('game_pk')} used market probability as model feature")
        surface = prediction.get("probabilities") or {}
        pairs = (
            (surface.get("away_ml"), surface.get("home_ml")),
            (surface.get("away_plus_1_5"), surface.get("home_minus_1_5")),
            (surface.get("home_plus_1_5"), surface.get("away_minus_1_5")),
            (surface.get("over"), surface.get("under")),
        )
        for left, right in pairs:
            if left is None or right is None or abs(float(left) + float(right) - 1.0) > 1e-9:
                raise ValueError(f"game {result.get('game_pk')} has invalid probability surface")


def build_persisted(
    *,
    target_date: str | None = None,
    destination: Path | str = V14_PAYLOAD,
    candidate_destination: Path | str = V14_CANDIDATE,
) -> dict[str, Any]:
    _validate_cutover_evidence()
    date = target_date or resolve_target_date()
    candidate = build_candidate(date)
    persist_candidate(candidate, candidate_destination)
    if not candidate.get("results"):
        raise SystemExit(f"native V14 acquisition produced no priced games for {date}")

    unauthorized = build_native_discord_payload(candidate)
    payload = authorize_payload(unauthorized, parity_authorized=True)
    payload["authorization_basis"] = {
        "type": "explicit-native-parity-cutover",
        **NATIVE_CUTOVER_EVIDENCE,
    }
    validate_production_payload(payload)

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"PULSAR_V14_NATIVE_PRODUCTION date={date} games={len(payload['results'])} path={target}")
    return payload


def send_persisted(*, path: Path | str = V14_PAYLOAD) -> None:
    source = Path(path)
    if not source.exists():
        raise SystemExit(f"V14 Discord payload absent: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    validate_production_payload(payload)

    ok = True
    for result in payload.get("results") or []:
        ok = bool(send_game(result)) and ok
    if not ok:
        raise SystemExit("Pulsar V14 Discord publication incomplete")
    print(f"PULSAR_V14_DISCORD published_games={len(payload.get('results') or [])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Native Pulsar V14 production runtime")
    parser.add_argument("--send-persisted", action="store_true")
    parser.add_argument("--target-date")
    parser.add_argument("--destination", default=str(V14_PAYLOAD))
    parser.add_argument("--candidate-destination", default=str(V14_CANDIDATE))
    args = parser.parse_args()
    if args.send_persisted:
        send_persisted(path=args.destination)
    else:
        build_persisted(
            target_date=args.target_date,
            destination=args.destination,
            candidate_destination=args.candidate_destination,
        )


if __name__ == "__main__":
    main()
