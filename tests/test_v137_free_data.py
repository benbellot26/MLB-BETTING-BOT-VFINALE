from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from v11 import v137_free_data as free
from v11 import v137_team_history as team


class FreeDataFoundationTests(unittest.TestCase):
    def test_ecmwf_run_uses_conservative_publication_lag(self):
        as_of = datetime(2026, 8, 19, 17, 30, tzinfo=timezone.utc)
        run = free.safe_ecmwf_run(as_of)
        self.assertEqual(run.isoformat(), "2026-08-19T06:00:00+00:00")
        self.assertTrue(free.weather_run_is_point_in_time(run, as_of))
        self.assertFalse(
            free.weather_run_is_point_in_time(
                datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc), as_of
            )
        )

    def test_weather_payload_refuses_future_run_and_selects_game_hour(self):
        payload = {
            "hourly": {
                "time": ["2026-08-19T18:00", "2026-08-19T19:00", "2026-08-19T20:00"],
                "temperature_2m": [20, 21, 22],
                "relative_humidity_2m": [55, 56, 57],
                "dew_point_2m": [10, 11, 12],
                "surface_pressure": [1000, 1001, 1002],
                "precipitation_probability": [1, 2, 3],
                "cloud_cover": [10, 20, 30],
                "wind_speed_10m": [8, 9, 10],
                "wind_direction_10m": [90, 100, 110],
                "wind_gusts_10m": [12, 13, 14],
            }
        }
        good = free.weather_from_single_run_payload(
            payload,
            "2026-08-19T19:10:00+00:00",
            "2026-08-19T06:00:00+00:00",
            "2026-08-19T17:30:00+00:00",
        )
        self.assertTrue(good["available"])
        self.assertTrue(good["point_in_time"])
        self.assertEqual(good["temperature_c"], 21.0)
        self.assertEqual(good["valid_hour"], "2026-08-19T19:00:00+00:00")

        bad = free.weather_from_single_run_payload(
            payload,
            "2026-08-19T19:10:00+00:00",
            "2026-08-19T12:00:00+00:00",
            "2026-08-19T17:30:00+00:00",
        )
        self.assertFalse(bad["available"])
        self.assertFalse(bad["point_in_time"])
        self.assertEqual(bad["reason"], "weather_run_not_public_by_as_of")

    def test_historical_weather_request_uses_single_run_and_ecmwf(self):
        calls = []

        def fake_fetch(url, params):
            calls.append((url, params))
            return {
                "hourly": {
                    "time": ["2026-08-19T19:00"],
                    "temperature_2m": [24],
                    "relative_humidity_2m": [50],
                    "dew_point_2m": [12],
                    "surface_pressure": [1005],
                    "precipitation_probability": [5],
                    "cloud_cover": [20],
                    "wind_speed_10m": [10],
                    "wind_direction_10m": [180],
                    "wind_gusts_10m": [15],
                }
            }

        out = free.historical_weather_for_game(
            "2026-08-19T19:00:00+00:00",
            "New York Yankees",
            "2026-08-19T17:00:00+00:00",
            fetch_json=fake_fetch,
        )
        self.assertTrue(out["available"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "https://single-runs-api.open-meteo.com/v1/forecast")
        self.assertEqual(calls[0][1]["models"], "ecmwf_ifs")
        self.assertEqual(calls[0][1]["run"], "2026-08-19T06:00")

    def test_statcast_is_stable_id_only_and_rejects_cutoff_day(self):
        prior = {
            "game_pk": "1",
            "at_bat_number": "1",
            "pitch_number": "1",
            "game_date": "2026-08-18",
            "batter": "100",
            "pitcher": "200",
            "events": "strikeout",
            "estimated_woba_using_speedangle": ".250",
            "launch_speed": "96",
            "launch_speed_angle": "6",
            "release_speed": "97",
            "pitch_type": "FF",
        }
        future = dict(prior)
        future.update(
            {
                "game_pk": "2",
                "game_date": "2026-08-19",
                "events": "walk",
                "release_speed": "90",
                "pitch_type": "SL",
            }
        )
        result = free.aggregate_statcast_priors([prior, dict(prior), future], "2026-08-19")
        self.assertTrue(result["stable_id_only"])
        self.assertEqual(set(result["hitters"]), {"100"})
        self.assertEqual(set(result["pitchers"]), {"200"})
        self.assertNotIn("player_name", json.dumps(result))
        self.assertEqual(result["diagnostics"]["accepted_pitch_rows"], 1)
        self.assertEqual(result["diagnostics"]["rejected_at_or_after_cutoff"], 1)
        self.assertAlmostEqual(result["pitchers"]["200"]["k_rate"], 1.0)
        self.assertEqual(result["pitchers"]["200"]["pitch_mix"], {"FF": 1.0})

    def test_reconstructed_envelope_can_never_be_native_promotion_evidence(self):
        row = free.reconstructed_feature_envelope(
            game_pk=7,
            game_time="2026-08-19T19:00:00+00:00",
            as_of="2026-08-19T17:00:00+00:00",
            home="A",
            away="B",
            features={"x": 1},
        )
        self.assertEqual(row["cohort"], free.COHORT)
        self.assertFalse(row["native_live"])
        self.assertFalse(row["promotion_eligible"])
        self.assertFalse(row["target_labels_embedded"])

    def test_team_history_keeps_target_label_separate_and_excludes_same_day(self):
        def game(pk, when, official, home_id, home, away_id, away, hs, aws):
            return {
                "gamePk": pk,
                "gameDate": when,
                "officialDate": official,
                "gameType": "R",
                "status": {"abstractGameState": "Final"},
                "teams": {
                    "home": {"team": {"id": home_id, "name": home}, "score": hs},
                    "away": {"team": {"id": away_id, "name": away}, "score": aws},
                },
                "venue": {"id": 1, "name": "Park"},
            }

        games = [
            game(1, "2026-08-17T18:00:00Z", "2026-08-17", 1, "A", 2, "B", 5, 2),
            game(2, "2026-08-19T16:00:00Z", "2026-08-19", 1, "A", 2, "B", 1, 0),
            game(3, "2026-08-19T21:00:00Z", "2026-08-19", 1, "A", 2, "B", 3, 4),
        ]
        features, labels, report = team.build_from_games(games)
        self.assertEqual(len(features), 3)
        self.assertEqual(len(labels), 3)
        target = next(r for r in features if str(r["game_pk"]) == "3")
        self.assertEqual(target["features"]["home_team_form"]["season_to_date"]["games"], 1)
        serialized = json.dumps(target)
        self.assertNotIn("home_score", serialized)
        self.assertNotIn("away_score", serialized)
        self.assertFalse(report["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
