from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path("data/v137_free_data_health.json")
SCHEMA = "v13-7-free-data-health-v4"


def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _coverage(available: Any, total: Any) -> float | None:
    try:
        n = int(total or 0)
        if n <= 0:
            return None
        return round(max(0.0, min(1.0, int(available or 0) / n)), 6)
    except Exception:
        return None


def build() -> dict[str, Any]:
    statcast = _load("data/v137_statcast_priors_report.json")
    team = _load("data/v137_free_team_history_report.json")
    weather = _load("data/v137_weather_backfill_report.json")
    park = _load("data/v137_park_factors_report.json")
    mlb_state = _load("data/v137_mlb_state_report.json")
    alerts: list[str] = []

    if statcast:
        if not statcast.get("stable_id_only"):
            alerts.append("statcast_not_stable_id_only")
        if not statcast.get("point_in_time"):
            alerts.append("statcast_not_point_in_time")
        if int(statcast.get("chunks_failed") or 0):
            alerts.append("statcast_chunk_failures")
        if statcast.get("unresolved_truncation"):
            alerts.append("statcast_unresolved_row_cap_truncation")
    else:
        alerts.append("statcast_priors_not_collected_yet")

    if team:
        if team.get("promotion_eligible"):
            alerts.append("reconstructed_team_history_must_not_be_native")
        if int(team.get("feature_rows") or 0) != int(team.get("label_rows") or 0):
            alerts.append("team_feature_label_count_mismatch")
    else:
        alerts.append("team_history_not_backfilled_yet")

    if weather:
        rows = int(weather.get("rows") or 0)
        pit = int(weather.get("point_in_time_rows") or 0)
        available = int(weather.get("available_rows") or 0)
        if rows and pit < rows:
            alerts.append("weather_point_in_time_gap")
        if rows and available == 0:
            alerts.append("weather_zero_available_rows")
        if weather.get("promotion_eligible"):
            alerts.append("reconstructed_weather_must_not_be_native")
    else:
        alerts.append("weather_backfill_not_collected_yet")

    if park:
        if park.get("promotion_eligible"):
            alerts.append("prior_park_factors_must_not_be_native")
        if int(park.get("failed_requests") or 0):
            alerts.append("park_factor_request_failures")
        if int(park.get("total_venue_rows") or 0) == 0:
            alerts.append("park_factor_zero_venue_rows")
        if int(park.get("empty_parse_count") or 0):
            alerts.append("park_factor_empty_parses")
        if int(park.get("window_rejection_count") or 0):
            alerts.append("park_factor_window_rejections")
        rolling = park.get("rolling_parameter")
        if rolling not in (None, 3):
            alerts.append("park_factor_wrong_rolling_window")
    else:
        alerts.append("prior_park_factors_not_collected_yet")

    if mlb_state:
        if not mlb_state.get("point_in_time") or not mlb_state.get("native_live"):
            alerts.append("mlb_state_snapshot_not_native_pit")
        if mlb_state.get("roster_failures"):
            alerts.append("mlb_roster_snapshot_failures")
        if mlb_state.get("transaction_error"):
            alerts.append("mlb_transaction_snapshot_failure")
    else:
        alerts.append("mlb_native_state_not_collected_yet")

    critical_alerts = {
        "statcast_not_stable_id_only",
        "statcast_not_point_in_time",
        "statcast_chunk_failures",
        "statcast_unresolved_row_cap_truncation",
        "team_feature_label_count_mismatch",
        "weather_point_in_time_gap",
        "weather_zero_available_rows",
        "park_factor_request_failures",
        "park_factor_zero_venue_rows",
        "park_factor_empty_parses",
        "park_factor_window_rejections",
        "park_factor_wrong_rolling_window",
        "mlb_state_snapshot_not_native_pit",
        "mlb_roster_snapshot_failures",
        "mlb_transaction_snapshot_failure",
    }
    unique_alerts = sorted(set(alerts))
    critical = sorted(x for x in unique_alerts if x in critical_alerts)
    status = "HEALTHY" if not unique_alerts else "DEGRADED" if critical else "PARTIAL"

    provider_metrics = {
        "weather_coverage": _coverage(weather.get("available_rows"), weather.get("rows")) if weather else None,
        "weather_pit_coverage": _coverage(weather.get("point_in_time_rows"), weather.get("rows")) if weather else None,
        "park_total_venue_rows": int(park.get("total_venue_rows") or 0) if park else None,
        "park_request_success_rate": (
            _coverage(
                int(park.get("requests_expected") or 0) - int(park.get("failed_requests") or 0),
                park.get("requests_expected"),
            )
            if park
            else None
        ),
        "roster_coverage": _coverage(mlb_state.get("rosters_ok"), 30) if mlb_state else None,
    }

    return {
        "schema": SCHEMA,
        "status": status,
        "critical_alerts": critical,
        "providers": {
            "mlb": "MLB Stats API (free)",
            "statcast": "Baseball Savant / Statcast Search CSV (free)",
            "park_factors": "Baseball Savant Statcast Park Factors (free)",
            "weather": "Open-Meteo Single Runs / ECMWF IFS (free)",
        },
        "paid_sources_required": False,
        "cohort_policy": {
            "historical_reconstructed": "research/challenger evidence only",
            "native_live": "authenticated live snapshots stay separate and may become eligible only through existing promotion gates",
        },
        "provider_metrics": provider_metrics,
        "team_history": team,
        "statcast": statcast,
        "park_factors": park,
        "mlb_native_state": mlb_state,
        "weather": weather,
        "alerts": unique_alerts,
        "claim": "data-health artifact only; reconstructed free data cannot masquerade as native-live evidence",
    }


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
