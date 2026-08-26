from __future__ import annotations

import unittest

from v14 import MODEL_GENERATION
from v14.historical_distribution_live_validation import build


ART={"status":"HISTORICAL_VALIDATED_SHADOW","source_run_id":32990513482,"frozen_at":"2026-08-26T15:31:43+00:00","dataset":{"dataset_content_sha256":"abc"},"candidate_parameters":{"dispersion":5.5,"environment_sigma":.16},"champion_parameters":{"dispersion":7.5,"environment_sigma":.08}}


def row(gid:int,analyzed:str,*,persisted:bool=True,source_run_id:int=32990513482,dataset_hash:str="abc"):
    shadow={"status":"READY_SHADOW","evidence_run_id":source_run_id,"dataset_content_sha256":dataset_hash,"candidate_parameters":{"dispersion":5.5,"environment_sigma":.16},"candidate_probabilities":{"home_ml":.56,"away_ml":.44,"home_minus_1_5":.41,"away_plus_1_5":.59,"away_minus_1_5":.24,"home_plus_1_5":.76,"over":.53,"under":.47}}
    training={"research_challengers":{"historical_distribution_shadow":shadow}} if persisted else {}
    return {"game_pk":str(gid),"game_date":"2026-08-27T20:00:00+00:00","analyzed_at":analyzed,"model_generation":MODEL_GENERATION,"settled":True,"home_score":5,"away_score":3,"home_mu":4.5,"away_mu":4.0,"total_line":8.5,"probabilities":{"home_ml":.55,"away_ml":.45,"home_minus_1_5":.40,"away_plus_1_5":.60,"away_minus_1_5":.25,"home_plus_1_5":.75,"over":.52,"under":.48},"training_features":training}


class HistoricalDistributionLiveValidationTests(unittest.TestCase):
    def test_pre_freeze_rows_never_count(self):
        out=build([row(1,"2026-08-26T15:00:00+00:00")],artifact=ART)
        self.assertEqual(out["games"],0);self.assertEqual(out["status"],"COLLECTING");self.assertFalse(out["auto_activation"])

    def test_post_freeze_persisted_rows_count_but_cannot_promote_below_floor(self):
        out=build([row(1,"2026-08-26T16:00:00+00:00"),row(2,"2026-08-26T16:01:00+00:00")],artifact=ART)
        self.assertEqual(out["games"],2);self.assertEqual(out["status"],"COLLECTING");self.assertEqual(out["minimum_prospective_games"],200);self.assertIn("persisted READY_SHADOW",out["evidence_contract"])

    def test_old_champion_only_rows_cannot_be_recomputed_into_prospective_evidence(self):
        out=build([row(1,"2026-08-26T16:00:00+00:00",persisted=False)],artifact=ART)
        self.assertEqual(out["games"],0);self.assertEqual(out["status"],"COLLECTING")

    def test_wrong_source_run_or_dataset_hash_fails_closed(self):
        rows=[row(1,"2026-08-26T16:00:00+00:00",source_run_id=1),row(2,"2026-08-26T16:01:00+00:00",dataset_hash="wrong")]
        out=build(rows,artifact=ART);self.assertEqual(out["games"],0)

    def test_later_duplicate_does_not_inflate_one_game(self):
        rows=[row(1,"2026-08-26T16:00:00+00:00"),row(1,"2026-08-26T17:00:00+00:00")]
        out=build(rows,artifact=ART);self.assertEqual(out["games"],1)


if __name__=="__main__":unittest.main()
