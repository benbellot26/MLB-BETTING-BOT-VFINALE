from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import v138_audit_features as advanced

STATCAST = Path("data/v137_statcast_priors_latest.json.gz")
STATCAST_REPORT = Path("data/v137_statcast_priors_report.json")
VERSION = "13.9-native-context-v1"


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if out.tzinfo is None:
            out = out.replace(tzinfo=timezone.utc)
        return out.astimezone(timezone.utc)
    except Exception:
        return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_gzip_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def load_statcast_priors(as_of: Any, game_date: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load only a daily Statcast prior that was already available by ``as_of``.

    This deliberately refuses today's filesystem artifact during historical
    replay when its generation timestamp is later than the replay timestamp.
    It also rejects a cutoff newer than the game date, preventing future pitch
    rows from entering a historical/live feature snapshot.
    """
    report = _load_json(STATCAST_REPORT)
    priors = _load_gzip_json(STATCAST)
    asof_dt = _dt(as_of)
    game_dt = _dt(game_date)
    generated = _dt(priors.get("generated_at"))
    cutoff = _dt((report.get("cutoff_day") or priors.get("cutoff_day")) and f"{report.get('cutoff_day') or priors.get('cutoff_day')}T00:00:00+00:00")

    provenance: dict[str, Any] = {
        "provider": "Baseball Savant stable-ID daily priors",
        "point_in_time": False,
        "used": False,
        "cutoff_day": report.get("cutoff_day") or priors.get("cutoff_day"),
        "generated_at": priors.get("generated_at"),
        "stable_id_only": bool(report.get("stable_id_only")),
        "unresolved_truncation": bool(report.get("unresolved_truncation")),
        "chunks_failed": int(report.get("chunks_failed") or 0),
    }

    if not priors or not report:
        provenance["reason"] = "statcast_prior_artifact_missing"
        return {}, provenance
    if not provenance["stable_id_only"]:
        provenance["reason"] = "statcast_prior_not_stable_id_only"
        return {}, provenance
    if provenance["unresolved_truncation"] or provenance["chunks_failed"]:
        provenance["reason"] = "statcast_prior_provider_integrity_failed"
        return {}, provenance
    if asof_dt is None or game_dt is None or generated is None:
        provenance["reason"] = "statcast_prior_timestamp_missing"
        return {}, provenance
    if generated > asof_dt:
        provenance["reason"] = "statcast_prior_generated_after_asof"
        return {}, provenance
    if cutoff is not None and cutoff.date() > game_dt.date():
        provenance["reason"] = "statcast_prior_cutoff_after_game"
        return {}, provenance

    lookback_end = _dt(
        f"{priors.get('lookback_end')}T23:59:59+00:00" if priors.get("lookback_end") else None
    )
    if lookback_end is not None and lookback_end.date() >= game_dt.date():
        provenance["reason"] = "statcast_prior_contains_game_day_or_future"
        return {}, provenance

    provenance.update(
        {
            "point_in_time": True,
            "used": True,
            "reason": "PIT_SAFE",
            "pitcher_ids": len(priors.get("pitchers") or {}),
            "hitter_ids": len(priors.get("hitters") or {}),
        }
    )
    return priors, provenance


def _park_prior(features: dict[str, Any]) -> dict[str, Any]:
    prior = features.get("park_prior") or {}
    if not prior.get("available"):
        return {"available": False}

    def value(side: str) -> Any:
        row = prior.get(side) or {}
        return row.get("park_factor_index") if isinstance(row, dict) else None

    return {
        "available": True,
        "ALL": value("all"),
        "LHB": value("l"),
        "RHB": value("r"),
    }


def _lineup_players(ctx: dict[str, Any], side: str) -> list[dict[str, Any]]:
    lineup = ctx.get(f"{side}_lineup") or {}
    if isinstance(lineup, dict):
        return list(lineup.get("players") or [])[:9]
    if isinstance(lineup, list):
        return list(lineup)[:9]
    return []


def build(result: dict[str, Any], as_of: Any = None) -> dict[str, Any]:
    """Build research-only advanced context from the actual live V13 result.

    No returned value is consumed by the champion probability path. The bridge
    exists so every advanced feature has a native collection/integration path
    and can accumulate evidence before any future promotion decision.
    """
    ctx = result.get("ctx") or {}
    features = result.get("features") or {}
    game_date = (result.get("game") or {}).get("gameDate")
    at = as_of or result.get("as_of") or datetime.now(timezone.utc).isoformat()
    statcast, statcast_meta = load_statcast_priors(at, game_date)
    bundle = advanced.build_advanced_context(result, statcast_priors=statcast)

    team_form = features.get("team_form") or features.get("team_forms") or {}
    if isinstance(team_form, dict):
        bundle["offense"] = {
            side: advanced.offense_talent(team_form.get(side) or {})
            for side in ("home", "away")
        }

    bundle["park"] = advanced.park_factor(_park_prior(features))
    bundle["lineup_ids"] = {
        side: [p.get("id") for p in _lineup_players(ctx, side) if p.get("id") is not None]
        for side in ("home", "away")
    }
    bundle.update(
        {
            "schema": "v13-9-native-research-context-v1",
            "version": VERSION,
            "as_of": str(at),
            "game_pk": str(result.get("game_pk") or ""),
            "research_only": True,
            "affects_champion": False,
            "market_data_embedded": False,
            "target_labels_embedded": False,
            "statcast_provenance": statcast_meta,
        }
    )
    return bundle


def attach(result: dict[str, Any], as_of: Any = None) -> dict[str, Any]:
    features = result.setdefault("features", {})
    if not isinstance(features, dict):
        raise TypeError("V13 result features must be a mapping")
    features["v139_native_research"] = build(result, as_of=as_of)
    return result
