import unittest
from datetime import datetime, timezone

from v14.acquisition import collect_pregame, future_games, match_events, mlb_schedule, odds_snapshot, resolve_target_date


def _game(pk, when, home="Home", away="Away"):
    return {"gamePk":pk,"gameDate":when,"teams":{"home":{"team":{"name":home}},"away":{"team":{"name":away}}}}


def _event(eid, when, home="Home", away="Away"):
    row={"id":eid,"home_team":home,"away_team":away}
    if when is not None: row["commence_time"]=when
    return row


class V14AcquisitionTests(unittest.TestCase):
    def test_target_date_matches_paris_slate_convention(self):
        self.assertEqual(resolve_target_date(now=datetime(2026,8,25,3,30,tzinfo=timezone.utc),override=""),"2026-08-24")
        self.assertEqual(resolve_target_date(now=datetime(2026,8,25,4,30,tzinfo=timezone.utc),override=""),"2026-08-25")
        self.assertEqual(resolve_target_date(override="2026-09-01"),"2026-09-01")
        with self.assertRaisesRegex(ValueError,"YYYY-MM-DD"): resolve_target_date(override="09/01/2026")

    def test_schedule_and_odds_contracts(self):
        def schedule_getter(url,params): self.assertEqual(params["sportId"],1); return {"dates":[{"games":[{"gamePk":1},{"gamePk":2}]}]}
        def odds_getter(url,params): self.assertEqual(params["markets"],"h2h,spreads,totals"); self.assertEqual(params["apiKey"],"secret"); return [{"id":"x"}]
        self.assertEqual(len(mlb_schedule("2026-08-25",getter=schedule_getter)),2); self.assertEqual(odds_snapshot(api_key="secret",getter=odds_getter),[{"id":"x"}])

    def test_matching_single_event_can_fallback_without_time(self):
        games=[{"gamePk":123,"teams":{"home":{"team":{"name":"New York Yankees"}},"away":{"team":{"name":"Boston Red Sox"}}}}]
        events=[{"id":"evt","home_team":"New York Yankees","away_team":"Boston Red Sox"}]
        self.assertEqual(match_events(games,events)["123"]["id"],"evt")

    def test_single_timed_event_outside_strict_window_is_rejected(self):
        matched=match_events([_game(1,"2026-08-25T17:00:00Z")],[_event("far","2026-08-25T18:30:00Z")])
        self.assertEqual(matched,{})

    def test_doubleheader_matching_uses_mutual_nearest_and_never_reuses_event(self):
        games=[_game(1,"2026-08-25T17:00:00Z"),_game(2,"2026-08-25T22:00:00Z")]
        events=[_event("late","2026-08-25T22:05:00Z"),_event("early","2026-08-25T17:05:00Z")]
        matched=match_events(games,events)
        self.assertEqual(matched["1"]["id"],"early"); self.assertEqual(matched["2"]["id"],"late"); self.assertEqual(len({v["id"] for v in matched.values()}),2)

    def test_doubleheader_missing_event_time_fails_closed(self):
        games=[_game(1,"2026-08-25T17:00:00Z"),_game(2,"2026-08-25T22:00:00Z")]
        events=[_event("early",None),_event("late","2026-08-25T22:05:00Z")]
        matched=match_events(games,events)
        self.assertNotIn("1",matched)
        self.assertEqual(matched.get("2",{}).get("id"),"late")

    def test_ambiguous_nearby_events_are_not_guessed(self):
        games=[_game(1,"2026-08-25T20:00:00Z"),_game(2,"2026-08-25T23:00:00Z")]
        # Game 1 is 10m from A and 20m from B: margin is only 10m, so no guess.
        events=[_event("a","2026-08-25T20:10:00Z"),_event("b","2026-08-25T20:20:00Z")]
        matched=match_events(games,events)
        self.assertNotIn("1",matched)

    def test_future_filter_fails_closed_on_bad_dates(self):
        games=[{"gamePk":1,"gameDate":"2026-08-25T20:00:00Z"},{"gamePk":2,"gameDate":"2026-08-25T17:00:00Z"},{"gamePk":3,"gameDate":"bad"}]
        self.assertEqual([g["gamePk"] for g in future_games(games,as_of="2026-08-25T18:00:00Z")],[1])

    def test_collect_pregame_never_marks_market_as_model_feature(self):
        def schedule_getter(url,params): return {"dates":[{"games":[_game(123,"2026-08-25T20:00:00Z")]}]}
        def odds_getter(url,params): return [_event("evt","2026-08-25T20:02:00Z")]
        snap=collect_pregame("2026-08-25",analyzed_at="2026-08-25T18:00:00Z",api_key="secret",schedule_getter=schedule_getter,odds_getter=odds_getter)
        self.assertIn("123",snap.matches); self.assertFalse(snap.as_dict()["market_probability_used_as_feature"])

    def test_odds_key_required(self):
        with self.assertRaisesRegex(RuntimeError,"ODDS_API_KEY"): odds_snapshot(api_key="",getter=lambda *_:[])

if __name__=="__main__": unittest.main()
