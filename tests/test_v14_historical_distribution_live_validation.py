from __future__ import annotations

import unittest

from v14 import MODEL_GENERATION
from v14.historical_distribution_live_validation import build


ART={"frozen_at":"2026-08-26T15:31:43+00:00","candidate_parameters":{"dispersion":5.5,"environment_sigma":.16},"champion_parameters":{"dispersion":7.5,"environment_sigma":.08}}


def row(gid:int,analyzed:str):
    return {"game_pk":str(gid),"game_date":"2026-08-27T20:00:00+00:00","analyzed_at":analyzed,"model_generation":MODEL_GENERATION,"settled":True,"home_score":5,"away_score":3,"home_mu":4.5,"away_mu":4.0,"total_line":8.5,"probabilities":{"home_ml":.55}}


class HistoricalDistributionLiveValidationTests(unittest.TestCase):
    def test_pre_freeze_rows_never_count(self):
        out=build([row(1,"2026-08-26T15:00:00+00:00")],artifact=ART)
        self.assertEqual(out["games"],0)
        self.assertEqual(out["status"],"COLLECTING")
        self.assertFalse(out["auto_activation"])

    def test_post_freeze_rows_count_but_cannot_promote_below_floor(self):
        out=build([row(1,"2026-08-26T16:00:00+00:00"),row(2,"2026-08-26T16:01:00+00:00")],artifact=ART)
        self.assertEqual(out["games"],2)
        self.assertEqual(out["status"],"COLLECTING")
        self.assertEqual(out["minimum_prospective_games"],200)


if __name__=="__main__":unittest.main()
