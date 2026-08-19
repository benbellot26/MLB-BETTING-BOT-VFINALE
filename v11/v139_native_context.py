from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import v137_park_factors as park_provider
from . import v138_audit_features as advanced

STATCAST = Path("data/v137_statcast_priors_latest.json.gz")
STATCAST_REPORT = Path("data/v137_statcast_priors_report.json")
MLB_STATE = Path("data/v137_mlb_state_latest.json.gz")
PARK_FACTORS = Path("data/v137_park_factors.json")
VERSION = "13.9-native-context-v2"


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
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
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
    """Load only a daily Statcast prior that was already available by ``as_of``."""
    report = _load_json(STATCAST_REPORT)
    priors = _load_gzip_json(STATCAST)
    asof_dt = _dt(as_of)
    game_dt = _dt(game_date)
    generated = _dt(priors.get("generated_at"))
    cutoff_day = report.get("cutoff_day") or priors.get("cutoff_day")
    cutoff = _dt(f"{cutoff_day}T00:00:00+00:00") if cutoff_day else None

    provenance: dict[str, Any] = {
        "provider": "Baseball Savant stable-ID daily priors",
        "point_in_time": False,
        "used": False,
        "cutoff_day": cutoff_day,
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


def load_mlb_state(as_of: Any, game_date: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a native MLB roster/transaction snapshot only when it existed by as-of."""
    state = _load_gzip_json(MLB_STATE)
    asof_dt = _dt(as_of)
    game_dt = _dt(game_date)
    observed = _dt(state.get("observed_at"))
    snapshot_day = state.get("snapshot_day")
    snapshot_dt = _dt(f"{snapshot_day}T00:00:00+00:00") if snapshot_day else None
    meta: dict[str, Any] = {
        "provider": "MLB Stats API native roster/transactions",
        "point_in_time": False,
        "used": False,
        "observed_at": state.get("observed_at"),
        "snapshot_day": snapshot_day,
    }
    if not state:
        meta["reason"] = "mlb_state_artifact_missing"
        return {}, meta
    if state.get("point_in_time") is not True or state.get("native_live") is not True:
        meta["reason"] = "mlb_state_contract_invalid"
        return {}, meta
    if asof_dt is None or game_dt is None or observed is None or snapshot_dt is None:
        meta["reason"] = "mlb_state_timestamp_missing"
        return {}, meta
    if observed > asof_dt:
        meta["reason"] = "mlb_state_observed_after_asof"
        return {}, meta
    if snapshot_dt.date() > game_dt.date():
        meta["reason"] = "mlb_state_snapshot_after_game"
        return {}, meta
    meta.update(
        {
            "point_in_time": True,
            "used": True,
            "reason": "PIT_SAFE",
            "rosters": len(state.get("active_rosters") or {}),
            "transactions": len(state.get("transactions") or []),
        }
    )
    return state, meta


def load_park_prior(result: dict[str, Any], game_date: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Join a completed-season Savant park prior for the game's venue/season."""
    artifact = _load_json(PARK_FACTORS)
    game_dt = _dt(game_date)
    venue = str(((result.get("game") or {}).get("venue") or {}).get("name") or "")
    meta: dict[str, Any] = {
        "provider": "Baseball Savant completed-season park factors",
        "point_in_time": False,
        "used": False,
        "venue": venue,
    }
    if not artifact or game_dt is None or not venue:
        meta["reason"] = "park_prior_artifact_or_venue_missing"
        return {}, meta
    prior = park_provider.venue_prior(artifact, game_dt.year, venue)
    source_end = prior.get("source_window_end_season")
    if not prior.get("available"):
        meta["reason"] = "park_prior_venue_unavailable"
        return {}, meta
    if source_end is None or int(source_end) >= game_dt.year:
        meta["reason"] = "park_prior_not_strictly_prior_season"
        return {}, meta
    meta.update(
        {
            "point_in_time": True,
            "used": True,
            "reason": "COMPLETED_SEASONS_ONLY",
            "source_window_end_season": int(source_end),
            "source_window_years": prior.get("source_window_years"),
        }
    )
    return prior, meta


def _park_factor_input(prior: dict[str, Any]) -> dict[str, Any]:
    if not prior.get("available"):
        return {"available": False}

    def index(key: str) -> Any:
        row = prior.get(key) or {}
        return row.get("park_factor_index") if isinstance(row, dict) else None

    return {
        "available": True,
        "ALL": index("all"),
        "LHB": index("l"),
        "RHB": index("r"),
    }


def _lineup_players(ctx: dict[str, Any], side: str) -> list[dict[str, Any]]:
    lineup = ctx.get(f"{side}_lineup") or {}
    if isinstance(lineup, dict):
        return list(lineup.get("players") or [])[:9]
    if isinstance(lineup, list):
        return list(lineup)[:9]
    return []


def _lineup_ids(ctx: dict[str, Any], side: str) -> list[int]:
    out = []
    for player in _lineup_players(ctx, side):
        try:
            if player.get("id") is not None:
                out.append(int(player["id"]))
        except Exception:
            continue
    return out


def _roster_context(state: dict[str, Any], ctx: dict[str, Any], side: str) -> dict[str, Any]:
    if not state:
        return {
            "available": False,
            "offense_factor": 1.0,
            "known_absent_ids": [],
            "known_absent_count": 0,
            "complete_injury_report": False,
        }
    team_id = ctx.get(f"{side}_id")
    roster = ((state.get("active_rosters") or {}).get(str(team_id)) or {}) if team_id is not None else {}
    if not roster or roster.get("error"):
        return {
            "available": False,
            "offense_factor": 1.0,
            "known_absent_ids": [],
            "known_absent_count": 0,
            "complete_injury_report": False,
        }
    roster_ids = [p.get("person_id") for p in roster.get("players") or [] if p.get("person_id") is not None]
    lineup_ids = _lineup_ids(ctx, side)
    relevant_ids = set(lineup_ids) | {int(x) for x in roster_ids}
    il_signals = [
        item
        for item in state.get("injured_list_transaction_signals") or []
        if item.get("person_id") is not None and int(item["person_id"]) in relevant_ids
    ]
    out = advanced.roster_availability(lineup_ids, roster_ids, il_signals)
    out["available"] = True
    out["team_id"] = team_id
    out["active_roster_players"] = len(roster_ids)
    return out


def build(result: dict[str, Any], as_of: Any = None) -> dict[str, Any]:
    """Build research-only native context without modifying Champion probabilities."""
    ctx = result.get("ctx") or {}
    features = result.get("features") or {}
    game_date = (result.get("game") or {}).get("gameDate")
    at = as_of or result.get("as_of") or datetime.now(timezone.utc).isoformat()

    statcast, statcast_meta = load_statcast_priors(at, game_date)
    state, state_meta = load_mlb_state(at, game_date)
    park_prior, park_meta = load_park_prior(result, game_date)
    bundle = advanced.build_advanced_context(result, statcast_priors=statcast)

    team_form = features.get("team_form") or features.get("team_forms") or {}
    if isinstance(team_form, dict):
        bundle["offense"] = {
            side: advanced.offense_talent(team_form.get(side) or {})
            for side in ("home", "away")
        }

    bundle["park"] = advanced.park_factor(_park_factor_input(park_prior))
    bundle["roster_availability"] = {
        side: _roster_context(state, ctx, side) for side in ("home", "away")
    }
    bundle["lineup_ids"] = {side: _lineup_ids(ctx, side) for side in ("home", "away")}
    bundle.update(
        {
            "schema": "v13-9-native-research-context-v2",
            "version": VERSION,
            "as_of": str(at),
            "game_pk": str(result.get("game_pk") or ""),
            "research_only": True,
            "affects_champion": False,
            "market_data_embedded": False,
            "target_labels_embedded": False,
            "statcast_provenance": statcast_meta,
            "mlb_state_provenance": state_meta,
            "park_provenance": park_meta,
        }
    )
    return bundle


def attach(result: dict[str, Any], as_of: Any = None) -> dict[str, Any]:
    features = result.setdefault("features", {})
    if not isinstance(features, dict):
        raise TypeError("V13 result features must be a mapping")
    features["v139_native_research"] = build(result, as_of=as_of)
    return result
