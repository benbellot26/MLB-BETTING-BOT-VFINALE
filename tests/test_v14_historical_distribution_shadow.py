from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from v14.historical_distribution_shadow import evaluate, load


class HistoricalDistributionShadowTests(unittest.TestCase):
    def test_repository_artifact_is_disabled_until_isolated_revalidation(self):
        # The previously validated artifact depended on run means from a
        # subsequently rejected challenger. Repository loading must fail closed
        # until fresh isolated full-holdout evidence is committed.
        self.assertEqual(load(),{})

    def test_hash_mismatch_rejects_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            ap=Path(td)/"a.json";mp=Path(td)/"m.json"
            ap.write_text(json.dumps({"schema":"pulsar-v14-historical-distribution-candidate-v1","status":"HISTORICAL_VALIDATED_SHADOW","auto_activation":False,"dataset":{"dataset_content_sha256":"a","feature_contract_sha256":"b"}}),encoding="utf-8")
            mp.write_text(json.dumps({"dataset_content_sha256":"x","feature_contract_sha256":"b"}),encoding="utf-8")
            self.assertEqual(load(ap,mp),{})

    def test_hash_matched_valid_artifact_can_be_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            ap=Path(td)/"a.json";mp=Path(td)/"m.json"
            ap.write_text(json.dumps({"schema":"pulsar-v14-historical-distribution-candidate-v1","status":"HISTORICAL_VALIDATED_SHADOW","auto_activation":False,"champion_impact":False,"dataset":{"dataset_content_sha256":"a","feature_contract_sha256":"b"}}),encoding="utf-8")
            mp.write_text(json.dumps({"dataset_content_sha256":"a","feature_contract_sha256":"b"}),encoding="utf-8")
            self.assertEqual(load(ap,mp).get("status"),"HISTORICAL_VALIDATED_SHADOW")

    def test_evaluate_produces_alternate_probabilities_without_champion_impact(self):
        prediction={"game_pk":"1","game_date":"2026-08-26T20:00:00Z","analyzed_at":"2026-08-26T18:00:00Z","phase":"FINAL","home":"Home","away":"Away","model_generation":"g","total_line":8.5,"run_projection":{"home_mu":4.6,"away_mu":4.1,"extra_innings_home_probability":.496},"probabilities":{"home_ml":.55,"away_ml":.45,"home_minus_1_5":.40,"away_plus_1_5":.60,"home_plus_1_5":.69,"away_minus_1_5":.31,"over":.52,"under":.48}}
        out=evaluate(prediction,artifact={"status":"HISTORICAL_VALIDATED_SHADOW","auto_activation":False,"candidate_parameters":{"dispersion":5.5,"environment_sigma":.16},"dataset":{"dataset_content_sha256":"x"},"source_run_id":1})
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertFalse(out["champion_impact"])
        self.assertAlmostEqual(out["candidate_probabilities"]["home_ml"]+out["candidate_probabilities"]["away_ml"],1.0)
        self.assertIn("home_ml",out["probability_delta"])


if __name__=="__main__":unittest.main()
