from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from v11 import v137_park_factors as park
from v11 import v137_weather_backfill as weather


class ProviderHardeningTests(unittest.TestCase):
    def test_previous_runs_offset_is_conservative_for_two_hour_cutoff(self):
        game = datetime(2026, 8, 19, 23, 0, tzinfo=timezone.utc)
        as_of = datetime(2026, 8, 19, 21, 0, tzinfo=timezone.utc)
        self.assertEqual(weather._previous_day_offset(game, as_of), 1)

    def test_previous_runs_offset_increases_for_older_cutoff(self):
        game = datetime(2026, 8, 19, 23, 0, tzinfo=timezone.utc)
        as_of = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(weather._previous_day_offset(game, as_of), 3)

    def test_previous_runs_refuses_postgame_analysis(self):
        game = datetime(2026, 8, 19, 23, 0, tzinfo=timezone.utc)
        self.assertIsNone(weather._previous_day_offset(game, game))

    def test_previous_runs_weather_uses_documented_fixed_lead_suffix(self):
        calls = []

        def fake_fetch(url, params):
            calls.append((url, dict(params)))
            suffix = "_previous_day1"
            return {
                "hourly": {
                    "time": ["2026-08-19T22:00", "2026-08-19T23:00"],
                    f"temperature_2m{suffix}": [21.0, 22.0],
                    f"relative_humidity_2m{suffix}": [55.0, 56.0],
                    f"dew_point_2m{suffix}": [11.0, 12.0],
                    f"surface_pressure{suffix}": [1004.0, 1005.0],
                    f"precipitation{suffix}": [0.0, 0.2],
                    f"cloud_cover{suffix}": [20.0, 30.0],
                    f"wind_speed_10m{suffix}": [8.0, 9.0],
                    f"wind_direction_10m{suffix}": [170.0, 180.0],
                    f"wind_gusts_10m{suffix}": [12.0, 13.0],
                }
            }

        result = weather.previous_run_weather_for_game(
            "2026-08-19T23:00:00+00:00",
            "New York Yankees",
            "2026-08-19T21:00:00+00:00",
            fetch_json=fake_fetch,
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["point_in_time"])
        self.assertTrue(result["provider_fallback"])
        self.assertEqual(result["previous_day_offset"], 1)
        self.assertEqual(result["temperature_c"], 22.0)
        self.assertIn("temperature_2m_previous_day1", calls[0][1]["hourly"])
        self.assertNotIn("models", calls[0][1])
        self.assertEqual(result["request_model"], "best_match")

    def test_park_provider_falls_back_when_savant_payload_is_empty(self):
        derived = [
            {
                "team": "Colorado Rockies",
                "venue": "Coors Field",
                "venue_id": 19,
                "year_label": "2023-2025",
                "park_factor_index": 112.0,
                "runs_index": 112.0,
                "source_method": "venue total runs per game divided by MLB total runs per game",
                "handedness_specific": False,
            }
        ]
        with patch.object(park, "_mlb_fallback_rows", return_value=derived):
            result = park.fetch_prior_factors(2026, "L", lambda *args, **kwargs: "<html></html>")
        self.assertEqual(result["parse_mode"], "mlb_stats_derived")
        self.assertTrue(result["provider_fallback"])
        self.assertFalse(result["handedness_specific"])
        self.assertEqual(result["source_window_years"], [2023, 2024, 2025])
        self.assertEqual(result["venue_count"], 1)
        self.assertEqual(result["rows"][0]["park_factor_index"], 112.0)
        self.assertFalse(result["promotion_eligible"])

    def test_park_fallback_uses_only_completed_source_seasons(self):
        calls = []

        def fake_games(season):
            calls.append(season)
            return [
                {
                    "gamePk": season,
                    "gameDate": f"{season}-07-01T20:00:00Z",
                    "status": {"abstractGameState": "Final"},
                    "teams": {
                        "home": {"team": {"name": "Colorado Rockies"}, "score": 6},
                        "away": {"team": {"name": "Opponent"}, "score": 4},
                    },
                    "venue": {"id": 19, "name": "Coors Field"},
                }
                for _ in range(20)
            ]

        park._MLB_FALLBACK_CACHE.clear()
        with patch.object(park, "_fetch_completed_season_games", side_effect=fake_games):
            rows = park._mlb_fallback_rows(2026)
        self.assertEqual(calls, [2023, 2024, 2025])
        self.assertTrue(rows)
        self.assertNotIn(2026, calls)
        self.assertEqual(rows[0]["year_label"], "2023-2025")


if __name__ == "__main__":
    unittest.main()
