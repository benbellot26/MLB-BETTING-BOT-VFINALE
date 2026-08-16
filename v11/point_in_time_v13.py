from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def validate_pregame_row(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    analyzed = _dt(row.get("analyzed_at") or row.get("as_of"))
    game_time = _dt(row.get("game_date") or ((row.get("game") or {}).get("gameDate")))
    if analyzed is None:
        reasons.append("analysis_timestamp_missing")
    if game_time is None:
        reasons.append("game_timestamp_missing")
    if analyzed is not None and game_time is not None and analyzed >= game_time:
        reasons.append("not_pregame")

    provenance = row.get("feature_provenance") or {}
    if not provenance:
        reasons.append("feature_provenance_missing")
    else:
        for name, meta in provenance.items():
            meta = meta or {}
            if meta.get("point_in_time") is not True:
                reasons.append(f"feature_not_point_in_time:{name}")
            observed = _dt(meta.get("observed_at") or meta.get("recorded_at"))
            if analyzed is not None and observed is not None and observed > analyzed:
                reasons.append(f"feature_observed_after_as_of:{name}")
            if meta.get("postgame_identity") is True:
                reasons.append(f"postgame_identity:{name}")
            if meta.get("season_aggregate") is True and not (meta.get("snapshot") or meta.get("cutoff_capable")):
                reasons.append(f"season_aggregate_without_cutoff:{name}")
    return not reasons, sorted(set(reasons))


def provenance_entry(
    source: str,
    *,
    as_of: str,
    observed_at: str | None = None,
    snapshot: bool = False,
    cutoff_capable: bool = False,
    season_aggregate: bool = False,
    postgame_identity: bool = False,
) -> dict[str, Any]:
    return {
        "source": source,
        "as_of": as_of,
        "observed_at": observed_at or as_of,
        "point_in_time": True,
        "snapshot": bool(snapshot),
        "cutoff_capable": bool(cutoff_capable),
        "season_aggregate": bool(season_aggregate),
        "postgame_identity": bool(postgame_identity),
    }


def mark_live_snapshot(result: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Attach conservative provenance to a live/replay result.

    HTTP replayed/current pregame payloads are accepted as snapshots. Historical
    reconstructed season aggregates must be marked separately by the reconstructor.
    """
    p = result.setdefault("feature_provenance", {})
    for name in ("team_stats", "starter_stats", "bullpen", "weather", "lineup"):
        p.setdefault(name, provenance_entry("recorded-live-source", as_of=as_of, snapshot=True))
    result["as_of"] = as_of
    return result
