from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path("data/v137_free_data_health.json")
SCHEMA = "v13-7-free-data-health-v1"


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
    alerts: list[str] = []

    if statcast:
        if not statcast.get("stable_id_only"):
            alerts.append("statcast_not_stable_id_only")
        if not statcast.get("point_in_time"):
            alerts.append("statcast_not_point_in_time")
        if int(statcast.get("chunks_failed") or 0):
            alerts.append("statcast_chunk_failures")
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
        if rows and pit < rows:
            alerts.append("weather_point_in_time_gap")
        if weather.get("promotion_eligible"):
            alerts.append("reconstructed_weather_must_not_be_native")
    else:
        alerts.append("weather_backfill_not_collected_yet")

    return {
        "schema": SCHEMA,
        "providers": {
            "mlb": "MLB Stats API (free)",
            "statcast": "Baseball Savant / Statcast Search CSV (free)",
            "weather": "Open-Meteo Single Runs / ECMWF IFS (free)",
        },
        "paid_sources_required": False,
        "cohort_policy": {
            "historical_reconstructed": "research/challenger evidence only",
            "native_live": "remains separate and is still required for production promotion gates",
        },
        "team_history": team,
        "statcast": statcast,
        "weather": weather,
        "alerts": sorted(set(alerts)),
        "claim": "data-health artifact only; reconstructed free data cannot masquerade as native-live evidence",
    }


def main() -> None:
    report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
