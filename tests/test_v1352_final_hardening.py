from __future__ import annotations

import unittest
from pathlib import Path

from v11 import probability_contract_v13 as contract
from v11 import v13_run_mean_runtime, v13_train


class V1352FinalHardeningTests(unittest.TestCase):
    def _row(self, *, game_pk=1, attach=True):
        row={
            "game_pk":game_pk,"phase":"FINAL",
            "analyzed_at":"2026-08-17T17:00:00+00:00","game_date":"2026-08-17T18:00:00+00:00",
            "home_score":5,"away_score":3,"home":"Home","away":"Away","features_from_postgame":False,
            "options":[{"market":"ML","name":"Home","is_canonical_line":True,"p_baseball_raw":.58,"result":"WIN"}],
        }
        if attach: contract.attach_contract(row)
        return row

    def test_predictive_contract_requires_exact_model_generation(self):
        current=self._row()
        self.assertTrue(contract.row_is_predictively_compatible(current))
        stale=self._row(game_pk=2)
        stale["predictive_contract"]["model_generation"]="older-generation"
        self.assertFalse(contract.row_is_predictively_compatible(stale))

    def test_exact_replay_marker_cannot_bypass_current_contract(self):
        exact=self._row(attach=False)
        exact["v13_evidence_tier"]="A_EXACT_REPLAY"
        self.assertEqual(v13_train.eligible_probability_rows([exact]),[])

    def test_final_run_mean_prior_is_gated_until_native_transfer_passes(self):
        collecting={
            "active":True,"historical_candidate_active":True,"phase_scope":"FINAL",
            "model_generation":contract.MODEL_GENERATION_FINGERPRINT,
            "exact_final_games":5,"exact_transfer_required_games":20,"exact_transfer_status":"COLLECTING_FINAL_ONLY",
            "model":{"home_bias":.1,"away_bias":.1,"slope_delta":0,"max_adjustment":.75},
        }
        h,a,meta=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",collecting)
        self.assertEqual((h,a),(5.0,4.0)); self.assertFalse(meta["active"])
        passed=dict(collecting); passed.update({"exact_final_games":20,"exact_transfer_status":"PASS_FINAL_ONLY"})
        h2,a2,meta2=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",passed)
        self.assertTrue(meta2["active"]); self.assertNotEqual((h2,a2),(5.0,4.0))

    def test_final_run_mean_prior_rejects_stale_generation_even_if_marked_active(self):
        stale={
            "active":True,"historical_candidate_active":True,"phase_scope":"FINAL",
            "model_generation":"older-generation","exact_final_games":50,
            "exact_transfer_required_games":20,"exact_transfer_status":"PASS_FINAL_ONLY",
            "model":{"home_bias":.1,"away_bias":.1,"slope_delta":0,"max_adjustment":.75},
        }
        h,a,meta=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",stale)
        self.assertEqual((h,a),(5.0,4.0)); self.assertFalse(meta["active"])
        self.assertEqual(meta["reason"],"FINAL_TRANSFER_MODEL_GENERATION_MISMATCH")

    def test_training_model_records_generation_and_excludes_replay_calibration(self):
        policy={
            "model_generation":contract.MODEL_GENERATION_FINGERPRINT,
            "training_policy":{"exact_v13_replay_backfill_allowed":False,"exact_replays_diagnostic_only":True},
        }
        self.assertEqual(policy["model_generation"],contract.MODEL_GENERATION_FINGERPRINT)
        self.assertFalse(policy["training_policy"]["exact_v13_replay_backfill_allowed"])

    def test_backfill_workflow_rebuilds_persists_and_runs_in_season(self):
        text=Path(".github/workflows/v13-historical-backfill.yml").read_text(encoding="utf-8")
        self.assertIn("python -m v11.v13_run_mean_prior", text)
        self.assertIn("data/v13_run_mean_prior.json", text)
        self.assertIn("PASS_FINAL_ONLY", text)
        self.assertIn("MODEL_GENERATION_FINGERPRINT", text)
        self.assertIn("cron: '30 10 * 3-11 *'", text)

    def test_runtime_metadata_separates_software_contract_and_generation(self):
        text=Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        self.assertIn('payload["software_version"] = VERSION', text)
        self.assertIn('payload["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION', text)
        self.assertIn('payload["model_generation"] = MODEL_GENERATION_FINGERPRINT', text)
        self.assertNotIn('payload["probability_contract_version"] = VERSION', text)

    def test_selector_labels_match_v1352_generation(self):
        text=Path("v11/selector.py").read_text(encoding="utf-8")
        self.assertIn('"selector_version": "V13.5.2-professional-portfolio-v1"', text)
        self.assertIn('"non retenu par V13.5.2"', text)
        self.assertNotIn('"non retenu par V13.5"', text)

    def test_self_test_allows_valid_future_prior_promotion(self):
        text=Path("v11/v13_entry.py").read_text(encoding="utf-8")
        self.assertNotIn('assert not mean_prior.get("active")', text)
        self.assertIn('if mean_prior.get("active"):', text)
        self.assertIn('assert observed >= required', text)
        self.assertIn('assert status == "PASS_FINAL_ONLY"', text)
        self.assertIn('MODEL_GENERATION_FINGERPRINT', text)


if __name__ == "__main__":
    unittest.main()
