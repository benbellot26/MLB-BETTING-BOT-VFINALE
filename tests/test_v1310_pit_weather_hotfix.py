from __future__ import annotations

import unittest

from v11 import point_in_time_v13 as pit


class V1310PITWeatherHotfixTests(unittest.TestCase):
    def test_weather_retrieved_after_requested_cutoff_advances_snapshot_time(self):
        row = {
            "game_date": "2026-08-19T23:00:00Z",
            "analyzed_at": "2026-08-19T19:25:00Z",
            "features": {
                "weather": {
                    "retrieved_at": "2026-08-19T19:25:04Z",
                    "forecast_reference_at": "2026-08-19T19:25:04Z",
                }
            },
        }
        pit.mark_live_snapshot(row, "2026-08-19T19:25:00Z")
        self.assertEqual(row["requested_as_of"], "2026-08-19T19:25:00Z")
        self.assertEqual(row["as_of"], "2026-08-19T19:25:04+00:00")
        self.assertEqual(row["analyzed_at"], row["as_of"])
        self.assertTrue(row["point_in_time"], row["point_in_time_validation"])
        self.assertNotIn(
            "feature_observed_after_as_of:weather",
            row["point_in_time_validation"]["reasons"],
        )

    def test_weather_after_first_pitch_still_fails_closed(self):
        row = {
            "game_date": "2026-08-19T19:25:03Z",
            "analyzed_at": "2026-08-19T19:25:00Z",
            "features": {
                "weather": {
                    "retrieved_at": "2026-08-19T19:25:04Z",
                }
            },
        }
        pit.mark_live_snapshot(row, "2026-08-19T19:25:00Z")
        self.assertFalse(row["point_in_time"])
        self.assertIn("not_pregame", row["point_in_time_validation"]["reasons"])

    def test_existing_later_feature_provenance_also_advances_snapshot_time(self):
        row = {
            "game_date": "2026-08-19T23:00:00Z",
            "analyzed_at": "2026-08-19T19:25:00Z",
            "features": {},
            "feature_provenance": {
                "lineup": pit.provenance_entry(
                    "test",
                    as_of="2026-08-19T19:25:00Z",
                    observed_at="2026-08-19T19:25:06Z",
                    snapshot=True,
                )
            },
        }
        pit.mark_live_snapshot(row, "2026-08-19T19:25:00Z")
        self.assertEqual(row["as_of"], "2026-08-19T19:25:06+00:00")
        self.assertTrue(row["point_in_time"], row["point_in_time_validation"])


if __name__ == "__main__":
    unittest.main()
