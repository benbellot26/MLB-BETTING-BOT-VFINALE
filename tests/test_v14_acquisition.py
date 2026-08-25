import unittest
from datetime import datetime, timezone

from v14.acquisition import collect_pregame, future_games, match_events, mlb_schedule, odds_snapshot, resolve_target_date


class V14AcquisitionTests(unittest.TestCase):
    def test_target_date_matches_paris_slate_convention(self):
        # 03:30 UTC = 05:30 Paris in summer: still previous MLB slate.
        self.assertEqual(
            resolve_target_date(now=datetime(2026, 8, 25, 3, 30, tzinfo=timezone.utc), override=""),
            "2026-08-24",
        )
        # 04:30 UTC = 06:30 Paris: current local calendar date.
        self.assertEqual(
            resolve_target_date(now=datetime(2026, 8, 25, 4, 30, tzinfo=timezone.utc), override=""),
            "2026-08-25",
        )
        self.assertEqual(resolve_target_date(override="2026-09-01"), "2026-09-01")
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            resolve_target_date(override="09/01/2026")

    def test_schedule_and_odds_contracts(self):
        def schedule_getter(url, params):
            self.assertEqual(params["sportId"], 1)
            return {"dates": [{"games": [{"gamePk": 1}, {"gamePk": 2}]}]}

        def odds_getter(url, params):
            self.assertEqual(params["markets"], "h2h,spreads,totals")
            self.assertEqual(params["apiKey"], "secret")
            return [{"id": "x"}]

        self.assertEqual(len(mlb_schedule("2026-08-25", getter=schedule_getter)), 2)
        self.assertEqual(odds_snapshot(api_key="secret", getter=odds_getter), [{"id": "x"}])

    def test_matching_is_team_identity_based(self):
        games = [{
            "gamePk": 123,
            "teams": {
                "home": {"team": {"name": "New York Yankees"}},
                "away": {"team": {"name": "Boston Red Sox"}},
            },
        }]
        events = [{"id": "evt", "home_team": "New York Yankees", "away_team": "Boston Red Sox"}]
        self.assertEqual(match_events(games, events)["123"]["id"], "evt")

    def test_future_filter_fails_closed_on_bad_dates(self):
        games = [
            {"gamePk": 1, "gameDate": "2026-08-25T20:00:00Z"},
            {"gamePk": 2, "gameDate": "2026-08-25T17:00:00Z"},
            {"gamePk": 3, "gameDate": "bad"},
        ]
        out = future_games(games, as_of="2026-08-25T18:00:00Z")
        self.assertEqual([g["gamePk"] for g in out], [1])

    def test_collect_pregame_never_marks_market_as_model_feature(self):
        def schedule_getter(url, params):
            return {"dates": [{"games": [{
                "gamePk": 123,
                "gameDate": "2026-08-25T20:00:00Z",
                "teams": {
                    "home": {"team": {"name": "Home"}},
                    "away": {"team": {"name": "Away"}},
                },
            }]}]}

        def odds_getter(url, params):
            return [{"id": "evt", "home_team": "Home", "away_team": "Away"}]

        snap = collect_pregame(
            "2026-08-25",
            analyzed_at="2026-08-25T18:00:00Z",
            api_key="secret",
            schedule_getter=schedule_getter,
            odds_getter=odds_getter,
        )
        self.assertIn("123", snap.matches)
        self.assertFalse(snap.as_dict()["market_probability_used_as_feature"])

    def test_odds_key_required(self):
        with self.assertRaisesRegex(RuntimeError, "ODDS_API_KEY"):
            odds_snapshot(api_key="", getter=lambda *_: [])


if __name__ == "__main__":
    unittest.main()
