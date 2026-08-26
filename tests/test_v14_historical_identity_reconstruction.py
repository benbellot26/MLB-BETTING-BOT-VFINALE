from __future__ import annotations

import unittest

from v14.historical_identity_reconstruction import extract


def team(base:int):
    players={}
    for slot in range(1,10):
        pid=base+slot
        players[f"ID{pid}"]={"person":{"id":pid},"battingOrder":str(slot*100),"stats":{"batting":{"atBats":4}}}
    starter=base+50
    players[f"ID{starter}"]={"person":{"id":starter},"stats":{"pitching":{"gamesStarted":1,"inningsPitched":"6.0"}}}
    # Substitute in slot 1 must not replace original starter identity.
    players[f"ID{base+99}"]={"person":{"id":base+99},"battingOrder":"101","stats":{"batting":{"atBats":1}}}
    return {"players":players}


class HistoricalIdentityReconstructionTests(unittest.TestCase):
    def test_extracts_original_lineups_and_starters_without_target_stats(self):
        out=extract(123,{"teams":{"home":team(1000),"away":team(2000)}})
        self.assertEqual(out["status"],"READY_DIAGNOSTIC")
        self.assertEqual(len(out["home"]["lineup_ids"]),9)
        self.assertEqual(out["home"]["lineup_ids"][0],"1001")
        self.assertEqual(out["home"]["starter_id"],"1050")
        self.assertFalse(out["performance_stats_from_target_game_used"])
        self.assertFalse(out["promotion_eligible"])
        self.assertTrue(out["native_live_confirmation_required"])

    def test_missing_identity_is_partial_not_imputed(self):
        out=extract(456,{"teams":{"home":{"players":{}},"away":{"players":{}}}})
        self.assertEqual(out["status"],"PARTIAL")
        self.assertTrue(out["missing"])


if __name__=="__main__":unittest.main()
