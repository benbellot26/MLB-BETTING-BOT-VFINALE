from __future__ import annotations

import unittest

from v14 import MODEL_GENERATION
from v14.historical_team_live_validation import build


def artifact():
    return {"status":"HISTORICAL_VALIDATED_SHADOW","source_run_id":7,"frozen_at":"2026-08-26T16:00:00+00:00","dataset":{"dataset_content_sha256":"abc"}}


def row(i:int,good:bool=True):
    day=27+(i//20);hour=i%20
    analyzed=f"2026-08-{day:02d}T{hour:02d}:00:00+00:00" if day<=31 else f"2026-09-{day-31:02d}T{hour:02d}:00:00+00:00"
    game=f"2026-09-30T23:00:00+00:00"
    champion={"home_ml":.52,"away_ml":.48,"home_minus_1_5":.42,"away_plus_1_5":.58,"away_minus_1_5":.25,"home_plus_1_5":.75,"over":.52,"under":.48}
    candidate={"home_ml":.62 if good else .42,"away_ml":.38 if good else .58,"home_minus_1_5":.52 if good else .32,"away_plus_1_5":.48 if good else .68,"away_minus_1_5":.18 if good else .35,"home_plus_1_5":.82 if good else .65,"over":.62 if good else .42,"under":.38 if good else .58}
    shadow={"status":"READY_SHADOW","evidence_run_id":7,"candidate_run_projection":{"home_mu":5.0 if good else 3.0,"away_mu":3.0 if good else 5.0},"candidate_probabilities":candidate}
    return {"model_generation":MODEL_GENERATION,"game_pk":str(i),"game_date":game,"analyzed_at":analyzed,"settled":True,"home_score":5,"away_score":3,"home_mu":4.2,"away_mu":4.0,"total_line":7.5,"probabilities":champion,"training_features":{"research_challengers":{"historical_team_run_shadow":shadow}}}


class HistoricalTeamLiveValidationTests(unittest.TestCase):
    def test_good_postfreeze_shadow_reaches_review_only(self):
        out=build([row(i) for i in range(200)],artifact())
        self.assertEqual(out["status"],"PROMOTION_REVIEW");self.assertTrue(out["gates"]["passes"]);self.assertFalse(out["auto_activation"]);self.assertFalse(out["champion_impact"])

    def test_too_few_games_stays_collecting(self):
        out=build([row(i) for i in range(50)],artifact());self.assertEqual(out["status"],"COLLECTING");self.assertFalse(out["gates"]["enough_games"])

    def test_worse_shadow_is_rejected_after_minimum(self):
        out=build([row(i,False) for i in range(200)],artifact());self.assertEqual(out["status"],"REJECTED_NATIVE_LIVE");self.assertFalse(out["gates"]["passes"])


if __name__=="__main__":unittest.main()
