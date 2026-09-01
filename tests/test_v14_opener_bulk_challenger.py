from __future__ import annotations

import unittest

from v14.opener_bulk_challenger import classify


class V14OpenerBulkChallengerTests(unittest.TestCase):
    def test_low_depth_starter_is_detected_without_fabricating_bulk_identity(self)->None:
        out=classify({"gamesStarted":10,"inningsPerStart":2.1,"inningsPitched":21.0})
        self.assertTrue(out["opener_like"])
        self.assertEqual(out["status"],"OPENER_DETECTED_BULK_IDENTITY_COLLECTING")
        self.assertIsNone(out["bulk_pitcher_identity"])
        self.assertFalse(out["champion_impact"])

    def test_normal_starter_is_not_reclassified(self)->None:
        out=classify({"gamesStarted":20,"inningsPerStart":5.6,"inningsPitched":112.0})
        self.assertEqual(out["status"],"ORDINARY_STARTER")
        self.assertFalse(out["champion_impact"])


if __name__=="__main__":unittest.main()
