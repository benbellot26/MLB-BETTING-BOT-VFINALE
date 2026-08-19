from __future__ import annotations

import urllib.error
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from v11 import v137_free_data_health as health
from v11 import v137_park_factors as park
from v11 import v137_weather_provider as weather
from v11 import v138_monitoring as monitoring


class V139ProviderHardeningTests(unittest.TestCase):
    def _weather_payload(self, hour="2026-08-19T19:00"):
        return {
            "hourly": {
                "time": [hour],
                "temperature_2m": [24],
                "relative_humidity_2m": [50],
                "dew_point_2m": [12],
                "surface_pressure": [1005],
                "precipitation": [0.2],
                "cloud_cover": [20],
                "wind_speed_10m": [10],
                "wind_direction_10m": [180],
                "wind_gusts_10m": [15],
            }
        }

    def test_park_factor_uses_real_three_year_rolling_parameter(self):
        calls = []
        html = """
        <table>
          <tr><th>Team</th><th>Venue</th><th>Year</th><th>Park Factor</th><th>R</th><th>HR</th><th>PA</th></tr>
          <tr><td>Rockies</td><td>Coors Field</td><td>2023-2025</td><td>112</td><td>125</td><td>105</td><td>56521</td></tr>
        </table>
        """

        def fake_fetch(url, params, timeout=30):
            calls.append((url, dict(params), timeout))
            return html

        result = park.fetch_prior_factors(2026, "L", fake_fetch)
        self.assertEqual(calls[0][1]["rolling"], 3)
        self.assertEqual(result["rolling_years"], 3)
        self.assertEqual(result["source_window_years"], [2023, 2024, 2025])
        self.assertEqual(result["expected_year_label"], "2023-2025")
        self.assertEqual(result["venue_count"], 1)
        self.assertEqual(result["rows"][0]["park_factor_index"], 112.0)
        self.assertFalse(result["promotion_eligible"])

    def test_park_factor_rejects_wrong_single_season_payload(self):
        html = """
        <table>
          <tr><th>Team</th><th>Venue</th><th>Year</th><th>Park Factor</th></tr>
          <tr><td>Rockies</td><td>Coors Field</td><td>2025</td><td>115</td></tr>
        </table>
        """
        result = park.fetch_prior_factors(2026, "", lambda *args, **kwargs: html)
        self.assertEqual(result["parsed_rows_before_window_check"], 1)
        self.assertEqual(result["rejected_window_rows"], 1)
        self.assertEqual(result["venue_count"], 0)

    def test_weather_fallback_keeps_exact_same_pit_run(self):
        calls = []

        def fake_fetch(url, params):
            calls.append(dict(params))
            if params["models"] == weather.PRIMARY_MODEL:
                raise urllib.error.HTTPError(url, 400, "bad request", None, None)
            return self._weather_payload()

        out = weather.historical_weather_for_game(
            "2026-08-19T19:00:00+00:00",
            "New York Yankees",
            "2026-08-19T17:00:00+00:00",
            fetch_json=fake_fetch,
        )
        self.assertTrue(out["available"])
        self.assertTrue(out["point_in_time"])
        self.assertTrue(out["fallback_used"])
        self.assertEqual(out["request_model"], weather.SECONDARY_MODEL)
        self.assertTrue(all(call["run"] == "2026-08-19T06:00" for call in calls))
        self.assertEqual(calls[0]["models"], weather.PRIMARY_MODEL)
        self.assertEqual(calls[-1]["models"], weather.SECONDARY_MODEL)

    def test_weather_reduced_profile_is_fail_neutral(self):
        calls = []

        def fake_fetch(url, params):
            calls.append(dict(params))
            if "relative_humidity_2m" in params["hourly"]:
                raise urllib.error.HTTPError(url, 400, "unsupported variable", None, None)
            payload = self._weather_payload()
            payload["hourly"].pop("relative_humidity_2m")
            return payload

        out = weather.historical_weather_for_game(
            "2026-08-19T19:00:00+00:00",
            "New York Yankees",
            "2026-08-19T17:00:00+00:00",
            fetch_json=fake_fetch,
        )
        self.assertTrue(out["available"])
        self.assertEqual(out["request_model"], weather.PRIMARY_MODEL)
        self.assertEqual(out["request_profile"], "reduced")
        self.assertIsNone(out["humidity_pct"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["run"], calls[1]["run"])

    def test_weather_pre_archive_never_falls_back_to_future_information(self):
        out = weather.historical_weather_for_game(
            "2024-03-10T19:00:00+00:00",
            "New York Yankees",
            "2024-03-10T17:00:00+00:00",
            fetch_json=lambda *args, **kwargs: self.fail("provider must not be called"),
        )
        self.assertFalse(out["available"])
        self.assertTrue(out["point_in_time"])
        self.assertEqual(out["reason"], "ecmwf_single_run_archive_not_available")

    def test_free_health_exposes_status_and_real_coverage(self):
        fixtures = {
            "data/v137_statcast_priors_report.json": {
                "stable_id_only": True,
                "point_in_time": True,
                "chunks_failed": 0,
                "unresolved_truncation": False,
            },
            "data/v137_free_team_history_report.json": {
                "promotion_eligible": False,
                "feature_rows": 100,
                "label_rows": 100,
            },
            "data/v137_weather_backfill_report.json": {
                "rows": 10,
                "point_in_time_rows": 10,
                "available_rows": 8,
                "promotion_eligible": False,
            },
            "data/v137_park_factors_report.json": {
                "promotion_eligible": False,
                "failed_requests": 0,
                "total_venue_rows": 540,
                "empty_parse_count": 0,
                "window_rejection_count": 0,
                "rolling_parameter": 3,
                "requests_expected": 18,
            },
            "data/v137_mlb_state_report.json": {
                "point_in_time": True,
                "native_live": True,
                "rosters_ok": 30,
                "roster_failures": [],
                "transaction_error": None,
            },
        }
        with patch.object(health, "_load", side_effect=lambda path: fixtures.get(path, {})):
            report = health.build()
        self.assertEqual(report["status"], "HEALTHY")
        self.assertEqual(report["provider_metrics"]["weather_coverage"], 0.8)
        self.assertEqual(report["provider_metrics"]["park_total_venue_rows"], 540)
        self.assertEqual(report["provider_metrics"]["roster_coverage"], 1.0)

    def test_monitoring_uses_total_park_rows_not_missing_legacy_key(self):
        fixtures = {
            "data/v137_free_data_health.json": {
                "status": "HEALTHY",
                "alerts": [],
                "provider_metrics": {"weather_coverage": 0.8, "weather_pit_coverage": 1.0},
            },
            "data/v137_mlb_state_report.json": {
                "rosters_ok": 30,
                "transactions": 12,
                "injured_list_transaction_signals": 3,
            },
            "data/v137_statcast_priors_report.json": {"rows": 150000},
            "data/v137_weather_backfill_report.json": {
                "available_rows": 8,
                "rows": 10,
                "fallback_rows": 2,
            },
            "data/v137_park_factors_report.json": {
                "total_venue_rows": 540,
                "failed_requests": 0,
                "empty_parse_count": 0,
                "window_rejection_count": 0,
                "rolling_parameter": 3,
            },
        }
        with patch.object(monitoring, "_load", side_effect=lambda path: fixtures.get(path, {})):
            snap = monitoring.provider_snapshot()
        self.assertEqual(snap["free_health_status"], "HEALTHY")
        self.assertEqual(snap["park_rows"], 540)
        self.assertEqual(snap["weather_coverage"], 0.8)


if __name__ == "__main__":
    unittest.main()
