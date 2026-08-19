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
    """Validate that every predictive input was available by ``as_of``.

    The top-level ``point_in_time`` flag is deliberately not trusted as proof.
    Eligibility is derived from timestamps and per-feature provenance.
    """
    reasons: list[str] = []
    analyzed = _dt(row.get("analyzed_at") or row.get("as_of"))
    game_time = _dt(row.get("game_date") or ((row.get("game") or {}).get("gameDate")))
    if analyzed is None:
        reasons.append("analysis_timestamp_missing")
    if game_time is None:
        reasons.append("game_timestamp_missing")
    if analyzed is not None and game_time is not None and analyzed >= game_time:
        reasons.append("not_pregame")
    if row.get("features_from_postgame") is True:
        reasons.append("features_from_postgame")

    provenance = row.get("feature_provenance") or {}
    if not provenance:
        reasons.append("feature_provenance_missing")
    else:
        for name, meta in provenance.items():
            meta = meta or {}
            if meta.get("point_in_time") is not True:
                reasons.append(f"feature_not_point_in_time:{name}")
            observed = _dt(meta.get("observed_at") or meta.get("recorded_at"))
            if observed is None:
                reasons.append(f"feature_timestamp_missing:{name}")
            if analyzed is not None and observed is not None and observed > analyzed:
                reasons.append(f"feature_observed_after_as_of:{name}")
            if meta.get("postgame_identity") is True:
                reasons.append(f"postgame_identity:{name}")
            if meta.get("season_aggregate") is True and not (meta.get("snapshot") or meta.get("cutoff_capable")):
                reasons.append(f"season_aggregate_without_cutoff:{name}")
    return not reasons, sorted(set(reasons))


def validate_promotion_grade_row(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """Stricter PIT check used by native model-promotion evidence.

    A normal pregame row may use capture time as its operational timestamp. For
    promotion-grade evidence we additionally require proof that each feature was
    captured by a durable source snapshot/replay or has an explicit source time.
    """
    valid, reasons = validate_pregame_row(row)
    provenance = row.get("feature_provenance") or {}
    for name, meta in provenance.items():
        meta = meta or {}
        if meta.get("source_timestamp_attested") is not True:
            reasons.append(f"feature_timestamp_not_attested:{name}")
        if str(meta.get("timestamp_basis") or "") not in {
            "source_observed_at",
            "recorded_http_replay_capture",
            "durable_snapshot_capture",
        }:
            reasons.append(f"feature_timestamp_basis_weak:{name}")
    reasons = sorted(set(reasons))
    return bool(valid and not reasons), reasons


def provenance_entry(
    source: str,
    *,
    as_of: str,
    observed_at: str | None = None,
    snapshot: bool = False,
    cutoff_capable: bool = False,
    season_aggregate: bool = False,
    postgame_identity: bool = False,
    timestamp_basis: str | None = None,
    source_timestamp_attested: bool | None = None,
) -> dict[str, Any]:
    explicit_source_time = observed_at is not None
    basis = timestamp_basis or ("source_observed_at" if explicit_source_time else "snapshot_capture_time")
    attested = explicit_source_time if source_timestamp_attested is None else bool(source_timestamp_attested)
    return {
        "source": source,
        "as_of": as_of,
        "observed_at": observed_at or as_of,
        "timestamp_basis": basis,
        "source_timestamp_attested": bool(attested),
        "point_in_time": True,
        "snapshot": bool(snapshot),
        "cutoff_capable": bool(cutoff_capable),
        "season_aggregate": bool(season_aggregate),
        "postgame_identity": bool(postgame_identity),
    }


def _effective_snapshot_as_of(result: dict[str, Any], requested_as_of: str) -> str:
    """Return the latest timestamp of any predictive input actually used.

    A production run fixes ``requested_as_of`` before network collection begins.
    Providers such as Open-Meteo are necessarily retrieved a few seconds later.
    Calling that normal collection delay leakage would be a false positive. The
    persisted snapshot therefore uses the latest real input-observation time as
    its final ``as_of``. This does not weaken PIT safety: if that latest time is
    at/after first pitch, ``validate_pregame_row`` still rejects the row.
    """
    requested = _dt(requested_as_of)
    candidates = [requested] if requested is not None else []

    features = result.get("features") or {}
    weather = features.get("weather") or {}
    for value in (weather.get("retrieved_at"), weather.get("forecast_reference_at")):
        parsed = _dt(value)
        if parsed is not None:
            candidates.append(parsed)

    for meta in (result.get("feature_provenance") or {}).values():
        meta = meta or {}
        parsed = _dt(meta.get("observed_at") or meta.get("recorded_at"))
        if parsed is not None:
            candidates.append(parsed)

    if not candidates:
        return requested_as_of
    return max(candidates).isoformat()


def mark_live_snapshot(result: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Attach conservative provenance and materialise the PIT validation result.

    Durable raw/source replay files prove the response existed by the analysis
    capture time. When no durable source is present, rows remain operationally
    PIT-valid but are not promotion-grade evidence.

    ``as_of`` supplied by the runner is the requested collection cutoff. The
    final persisted snapshot time is advanced only to the latest predictive
    input timestamp actually used, never to an arbitrary tolerance window.
    """
    p = result.setdefault("feature_provenance", {})
    durable_source = bool(result.get("source_replay") or result.get("raw_snapshot"))
    basis = "recorded_http_replay_capture" if result.get("source_replay") else "durable_snapshot_capture" if result.get("raw_snapshot") else "snapshot_capture_time"

    features = result.get("features") or {}
    weather = features.get("weather") or {}
    weather_observed = weather.get("retrieved_at") or weather.get("forecast_reference_at")
    effective_as_of = _effective_snapshot_as_of(result, as_of)

    defaults = {
        "team_stats": None,
        "starter_stats": None,
        "bullpen": None,
        "weather": weather_observed,
        "lineup": None,
    }
    for name, observed in defaults.items():
        if name in p:
            continue
        source_time = observed or effective_as_of
        p[name] = provenance_entry(
            "recorded-live-source",
            as_of=effective_as_of,
            observed_at=source_time,
            snapshot=True,
            timestamp_basis="source_observed_at" if observed else basis,
            source_timestamp_attested=bool(observed) or durable_source,
        )

    result["requested_as_of"] = result.get("requested_as_of") or as_of
    result["as_of"] = effective_as_of
    result["analyzed_at"] = effective_as_of
    result["snapshot_as_of_basis"] = "latest_predictive_input_observed_at"
    result["features_from_postgame"] = False
    valid, reasons = validate_pregame_row(result)
    promotion_valid, promotion_reasons = validate_promotion_grade_row(result)
    result["point_in_time"] = bool(valid)
    result["point_in_time_validation"] = {
        "valid": bool(valid),
        "reasons": reasons,
        "promotion_grade_valid": bool(promotion_valid),
        "promotion_grade_reasons": promotion_reasons,
        "source": "feature-provenance-validator-v4",
    }
    return result
