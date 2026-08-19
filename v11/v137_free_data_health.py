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


def build() -> dict[str, Any]:
    statcast = _load("data/v137_statcast_priors_report.json")
    team = _load("data/v137_free_team_history_report.json")
    weather = _load("data/v137_weather_backfill_report.json")
    park = _load("data/v137_park_factors_report.json")
    mlb_state = _load("data/v137_mlb_state_report.json")
    alerts: list[str] = []
    warnings: list[str] = []

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
        elif rows and available < rows:
            warnings.append("weather_partial_coverage")
        provider_counts = weather.get("provider_counts") or {}
        if any("Previous Runs" in str(name) and int(count or 0) > 0 for name, count in provider_counts.items()):
            warnings.append("weather_previous_runs_fallback_used")
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
        if int(park.get("fallback_requests") or 0):
            warnings.append("park_factor_mlb_stats_fallback_used")
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

    alerts = sorted(set(alerts))
    warnings = sorted(set(warnings))
    status = "FAIL" if alerts else "DEGRADED" if warnings else "HEALTHY"
    return {
        "schema": SCHEMA,
        "status": status,
        "providers": {
            "mlb": "MLB Stats API (free)",
            "statcast": "Baseball Savant / Statcast Search CSV (free)",
            "park_factors": "Baseball Savant preferred; MLB Stats prior-season fallback (free)",
            "weather": "Open-Meteo Single Runs preferred; Previous Runs fallback (free)",
        },
        "paid_sources_required": False,
        "cohort_policy": {
            "historical_reconstructed": "research/challenger evidence only",
            "native_live": "authenticated live snapshots stay separate and may become eligible only through existing promotion gates",
        },
        "team_history": team,
        "statcast": statcast,
        "park_factors": park,
        "mlb_native_state": mlb_state,
        "weather": weather,
        "alerts": alerts,
        "warnings": warnings,
        "claim": "data-health artifact only; reconstructed free data cannot masquerade as native-live evidence",
    }


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
