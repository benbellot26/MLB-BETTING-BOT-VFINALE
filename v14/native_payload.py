from __future__ import annotations

"""Build the final V14 production payload from native acquisition results only."""

from copy import deepcopy
from typing import Any

from . import MODEL_GENERATION, VERSION


def native_result_for_discord(result: dict[str, Any]) -> dict[str, Any]:
    prediction = deepcopy(result.get("v14_prediction") or {})
    if prediction.get("role") != "PRODUCTION":
        raise ValueError("native result missing production prediction")
    if prediction.get("model_generation") != MODEL_GENERATION:
        raise ValueError("native result generation mismatch")
    if prediction.get("market_probability_used_as_feature") is not False:
        raise ValueError("market probability feature leak")

    game_pk = str(result.get("game_pk") or prediction.get("game_pk") or "")
    game_date = str(result.get("game_date") or prediction.get("game_date") or "")
    analyzed_at = str(result.get("analyzed_at") or prediction.get("analyzed_at") or "")
    home = str(result.get("home") or prediction.get("home") or "")
    away = str(result.get("away") or prediction.get("away") or "")
    if not all((game_pk, game_date, analyzed_at, home, away)):
        raise ValueError("native result missing Discord identity")

    line = prediction.get("total_line")
    if line is None:
        line = (result.get("canonical_lines") or {}).get("TOTAL")
    if line is None:
        raise ValueError("native result missing total line")

    return {
        "game_pk": game_pk,
        "game_date": game_date,
        "analyzed_at": analyzed_at,
        "phase": str(result.get("phase") or prediction.get("phase") or "EARLY").upper(),
        "home": home,
        "away": away,
        "ctx": deepcopy(result.get("ctx") or {}),
        "canonical_lines": {"TOTAL": float(line)},
        "line_selection": deepcopy(result.get("line_selection") or {}),
        "market_snapshot": deepcopy(result.get("market_snapshot") or {}),
        "market_diagnostics": deepcopy(result.get("market_diagnostics") or {}),
        "starter_fallback": deepcopy(result.get("starter_fallback") or {}),
        "v14_prediction": prediction,
        "model_generation": MODEL_GENERATION,
        "model": {"version": VERSION, "generation": MODEL_GENERATION, "role": "PRODUCTION"},
        "market_probability_used_as_feature": False,
        "native_acquisition": True,
        "legacy_acquisition_adapter": False,
    }


def build_native_discord_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("role") != "CANDIDATE_NON_PUBLISHING":
        raise ValueError("expected non-publishing native candidate")
    if candidate.get("native_acquisition") is not True:
        raise ValueError("candidate is not native acquisition")
    if candidate.get("legacy_acquisition_adapter") is not False:
        raise ValueError("candidate still depends on legacy acquisition")
    if candidate.get("market_probability_used_as_feature") is not False:
        raise ValueError("candidate market probability feature leak")

    results = [native_result_for_discord(result) for result in candidate.get("results") or []]
    return {
        "schema": "pulsar-v14-native-discord-payload-v2",
        "version": VERSION,
        "model_generation": MODEL_GENERATION,
        "role": "PRODUCTION_PAYLOAD_UNAUTHORIZED",
        "publication_authorized": False,
        "native_acquisition": True,
        "legacy_acquisition_adapter": False,
        "legacy_probability_used_for_publication": False,
        "market_probability_used_as_feature": False,
        "target_date": candidate.get("target_date"),
        "analyzed_at": candidate.get("analyzed_at"),
        "results": results,
        "chosen": [],
        "combo": {},
        "coverage": deepcopy(candidate.get("coverage") or {}),
    }


def authorize_payload(payload: dict[str, Any], *, production_authorized: bool) -> dict[str, Any]:
    """Explicit production switch; migration/parity is no longer a runtime dependency."""
    if not production_authorized:
        raise ValueError("native production publication is not authorized")
    if payload.get("role") != "PRODUCTION_PAYLOAD_UNAUTHORIZED":
        raise ValueError("unexpected native payload role")
    if payload.get("publication_authorized") is not False:
        raise ValueError("native payload was already authorized")
    out = deepcopy(payload)
    out["role"] = "PRODUCTION"
    out["publication_authorized"] = True
    out["authorization_basis"] = "native-v14-production-contract"
    return out
