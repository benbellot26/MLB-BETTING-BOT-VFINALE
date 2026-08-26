import unittest

from v14.starter_recent_usage import enrich_starter, recent_starts
from v14.starter_usage_challenger import estimate


class V14StarterRecentUsageTests(unittest.TestCase):
    def test_same_day_and_future_game_logs_are_rejected(self):
        def getter(_url,_params):
            return {"stats":[{"splits":[
                {"date":"2026-08-24","stat":{"gamesStarted":1,"inningsPitched":"4.0","numberOfPitches":72,"battersFaced":18}},
                {"date":"2026-08-25","stat":{"gamesStarted":1,"inningsPitched":"9.0","numberOfPitches":100,"battersFaced":30}},
                {"date":"2026-08-26","stat":{"gamesStarted":1,"inningsPitched":"9.0","numberOfPitches":100,"battersFaced":30}},
            ]}]}
        rows=recent_starts(99,2026,"2026-08-25T23:00:00Z",getter=getter)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["game_date"],"2026-08-24")
        self.assertEqual(rows[0]["pitches"],72.0)

    def test_provider_failure_is_fail_soft_for_shadow_only_feature(self):
        def broken(_url,_params): raise RuntimeError("provider unavailable")
        starter={"id":99,"inningsPitched":72.0,"gamesStarted":12,"inningsPerStart":6.0}
        enriched=enrich_starter(starter,"2026-08-25T23:00:00Z",getter=broken)
        self.assertEqual(enriched["recent_starts"],[])
        self.assertEqual(enriched["recent_starts_status"],"COLLECTING")
        out=estimate(enriched)
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertAlmostEqual(out["expected_innings"],6.0,places=8)
        self.assertFalse(out["auto_activation"])

    def test_collected_short_leash_reduces_expected_innings_only_in_shadow(self):
        def getter(_url,_params):
            return {"stats":[{"splits":[
                {"date":"2026-08-24","stat":{"gamesStarted":1,"inningsPitched":"4.0","numberOfPitches":72}},
                {"date":"2026-08-18","stat":{"gamesStarted":1,"inningsPitched":"4.1","numberOfPitches":74}},
                {"date":"2026-08-12","stat":{"gamesStarted":1,"inningsPitched":"4.2","numberOfPitches":75}},
            ]}]}
        base={"id":99,"inningsPitched":72.0,"gamesStarted":12,"inningsPerStart":6.0}
        enriched=enrich_starter(base,"2026-08-25T23:00:00Z",getter=getter)
        out=estimate(enriched)
        self.assertEqual(enriched["recent_starts_n"],3)
        self.assertLess(out["expected_innings"],6.0)
        self.assertGreater(out["expected_bullpen_innings"],3.0)
        self.assertFalse(out["auto_activation"])


if __name__=="__main__": unittest.main()
