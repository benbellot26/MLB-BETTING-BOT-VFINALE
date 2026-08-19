from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from v11 import v137_free_data as free
from v11 import v137_team_history as team
from v11 import v137_park_factors as park
from v11 import v137_mlb_state as mlb_state


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
                "precipitation": [0.0, 0.4, 0.8],
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
        self.assertEqual(good["precipitation_mm"], 0.4)
        self.assertIsNone(good["precip_probability"])
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

    def test_historical_weather_request_uses_supported_ecmwf_variables(self):
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
                    "precipitation": [0.2],
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
        self.assertIn("precipitation", calls[0][1]["hourly"])
        self.assertNotIn("precipitation_probability", calls[0][1]["hourly"])

    def test_statcast_adaptive_fetch_splits_capped_ranges(self):
        calls = []

        def fake_fetch(url, params, timeout=45):
            start = params["game_date_gt"]
            end = params["game_date_lt"]
            calls.append((start, end))
            count = 2 if start == end else 5
            lines = ["game_date,batter,pitcher,game_pk,at_bat_number,pitch_number"]
            for i in range(count):
                token = start.replace("-", "") + end.replace("-", "") + str(i)
                lines.append(f"{start},100,200,{token},{i+1},1")
            return "\n".join(lines) + "\n"

        rows, diag = free.fetch_statcast_rows_adaptive(
            "2026-08-17", "2026-08-19", fetch_text=fake_fetch, season=2026, row_cap=5
        )
        self.assertEqual(len(rows), 6)
        self.assertGreaterEqual(diag["cap_hits"], 2)
        self.assertGreaterEqual(diag["splits"], 2)
        self.assertFalse(diag["unresolved_truncation"])
        self.assertEqual(len(calls), 5)

    def test_statcast_single_day_cap_fails_closed(self):
        def fake_fetch(url, params, timeout=45):
            lines = ["game_date,batter,pitcher,game_pk,at_bat_number,pitch_number"]
            for i in range(5):
                lines.append(f"2026-08-18,100,200,{i},{i+1},1")
            return "\n".join(lines) + "\n"

        with self.assertRaisesRegex(RuntimeError, "statcast_single_day_row_cap"):
            free.fetch_statcast_rows_adaptive(
                "2026-08-18", "2026-08-18", fetch_text=fake_fetch, season=2026, row_cap=5
            )

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

    def test_prior_park_factor_parses_static_table_and_excludes_target_season(self):
        calls = []
        html = """
        <table>
          <tr><th>Team</th><th>Venue</th><th>Year</th><th>Park Factor</th><th>wOBAcon</th><th>xwOBAcon</th><th>HardHit</th><th>R</th><th>HR</th><th>PA</th></tr>
          <tr><td>Rockies</td><td>Coors Field</td><td>2023-2025</td><td>113</td><td>112</td><td>101</td><td>100</td><td>128</td><td>106</td><td>48000</td></tr>
        </table>
        """

        def fake_fetch(url, params, timeout=30):
            calls.append((url, dict(params), timeout))
            return html

        result = park.fetch_prior_factors(2026, "L", fake_fetch)
        self.assertEqual(result["target_season"], 2026)
        self.assertEqual(result["source_window_years"], [2023, 2024, 2025])
        self.assertNotIn(2026, result["source_window_years"])
        self.assertEqual(calls[0][1]["year"], 2025)
        self.assertEqual(calls[0][1]["rolling"], 1)
        self.assertEqual(calls[0][1]["batSide"], "L")
        self.assertEqual(result["parse_mode"], "html_table")
        self.assertEqual(result["rows"][0]["park_factor_index"], 113.0)
        self.assertFalse(result["promotion_eligible"])

    def test_prior_park_factor_parses_savant_embedded_json(self):
        html = """
        <html><script>
        var something = 1;
        data = [{"team_name":"Rockies","venue_name":"Coors Field","venue_id":19,
                 "year":"2023-2025","index_woba":113,"index_wobacon":112,
                 "index_xwobacon":101,"index_hardhit":100,"index_r":128,
                 "index_hr":106,"pa":48000}];
        </script></html>
        """
        result = park.fetch_prior_factors(2026, "R", lambda *args, **kwargs: html)
        self.assertEqual(result["parse_mode"], "embedded_json")
        self.assertEqual(result["venue_count"], 1)
        self.assertEqual(result["rows"][0]["venue"], "Coors Field")
        self.assertEqual(result["rows"][0]["park_factor_index"], 113.0)
        self.assertEqual(result["rows"][0]["hr_index"], 106.0)

        artifact = {"seasons": {"2026": {"L": result, "ALL": result, "R": result}}}
        venue = park.venue_prior(artifact, 2026, "Coors Field")
        self.assertTrue(venue["available"])
        self.assertEqual(venue["source_window_end_season"], 2025)
        self.assertEqual(venue["r"]["hr_index"], 106.0)

    def test_mlb_native_state_uses_stable_roster_ids_and_conservative_il_signal(self):
        def fake_mlb(path, params=None):
            if path == "v1/teams":
                return {"teams": [{"id": 99, "name": "Test Club", "abbreviation": "TST"}]}
            if path == "v1/teams/99/roster":
                return {
                    "roster": [
                        {
                            "person": {"id": 123, "fullName": "Player One"},
                            "position": {"code": "1", "abbreviation": "P"},
                            "status": {"code": "A", "description": "Active"},
                        }
                    ]
                }
            if path == "v1/transactions":
                return {
                    "transactions": [
                        {
                            "id": 1,
                            "person": {"id": 456, "fullName": "Player Two"},
                            "toTeam": {"id": 99, "name": "Test Club"},
                            "date": "2026-08-19",
                            "effectiveDate": "2026-08-19",
                            "typeCode": "SC",
                            "typeDesc": "Status Change",
                            "description": "Placed on the 10-day injured list",
                        }
                    ]
                }
            raise AssertionError(path)

        with patch.object(mlb_state.core, "mlb", side_effect=fake_mlb):
            artifact, report = mlb_state.collect("2026-08-19", 14)
        self.assertTrue(artifact["point_in_time"])
        self.assertTrue(artifact["native_live"])
        self.assertFalse(artifact["promotion_eligible"])
        self.assertEqual(artifact["active_rosters"]["99"]["players"][0]["person_id"], 123)
        self.assertEqual(len(artifact["transactions"]), 1)
        self.assertTrue(artifact["transactions"][0]["injured_list_signal"])
        self.assertEqual(report["rosters_ok"], 1)
        self.assertEqual(report["injured_list_transaction_signals"], 1)

    def test_team_history_keeps_target_label_separate_excludes_same_day_and_uses_prior_park(self):
        def game(pk, when, official, home_id, home, away_id, away, hs, aws, game_type="R"):
            return {
                "gamePk": pk,
                "gameDate": when,
                "officialDate": official,
                "gameType": game_type,
                "status": {"abstractGameState": "Final"},
                "teams": {
                    "home": {"team": {"id": home_id, "name": home}, "score": hs},
                    "away": {"team": {"id": away_id, "name": away}, "score": aws},
                },
                "venue": {"id": 1, "name": "Park"},
            }

        park_payload = {
            "source_window_end_season": 2025,
            "rows": [
                {
                    "venue": "Park",
                    "park_factor_index": 105.0,
                    "hr_index": 102.0,
                }
            ],
        }
        park_artifact = {
            "seasons": {
                "2026": {"ALL": park_payload, "L": park_payload, "R": park_payload}
            }
        }
        games = [
            game(1, "2026-08-17T18:00:00Z", "2026-08-17", 1, "A", 2, "B", 5, 2),
            game(2, "2026-08-19T16:00:00Z", "2026-08-19", 1, "A", 2, "B", 1, 0),
            game(3, "2026-08-19T21:00:00Z", "2026-08-19", 1, "A", 2, "B", 3, 4),
            game(4, "2026-10-05T20:00:00Z", "2026-10-05", 1, "A", 2, "B", 9, 8, game_type="P"),
        ]
        features, labels, report = team.build_from_games(games, park_artifact=park_artifact)
        self.assertEqual(len(features), 3)
        self.assertEqual(len(labels), 3)
        self.assertEqual(report["skipped"].get("non_regular_season"), 1)
        self.assertEqual(report["park_prior_rows"], 3)
        target = next(r for r in features if str(r["game_pk"]) == "3")
        self.assertEqual(target["features"]["home_team_form"]["season_to_date"]["games"], 1)
        self.assertTrue(target["features"]["park_prior"]["available"])
        self.assertEqual(target["features"]["park_prior"]["source_window_end_season"], 2025)
        serialized = json.dumps(target)
        self.assertNotIn("home_score", serialized)
        self.assertNotIn("away_score", serialized)
        self.assertFalse(report["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
