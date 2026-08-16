import json
import unittest
from pathlib import Path

from v11 import v13_run_mean_runtime as runtime


class RunMeanPriorTests(unittest.TestCase):
    def test_persisted_artifact_is_active_and_safe(self):
        d=json.loads(Path("data/v13_run_mean_prior.json").read_text(encoding="utf-8"))
        self.assertTrue(d["active"])
        self.assertEqual(d["phase_scope"],"FINAL")
        self.assertFalse(d["safety"]["historical_odds_used"])
        self.assertFalse(d["safety"]["market_probability_used"])
        self.assertGreaterEqual(d["exact_games"],20)
        self.assertGreater(d["test"]["rmse_gain"],0)
        self.assertGreater(d["exact_transfer"]["nll_gain"],0)

    def test_non_final_is_identity(self):
        h,a,meta=runtime.apply_pair(5.0,4.0,"LATE")
        self.assertEqual((h,a),(5.0,4.0))
        self.assertFalse(meta["active"])

    def test_final_applies_bounded_adjustment(self):
        h,a,meta=runtime.apply_pair(5.0,4.0,"FINAL")
        self.assertTrue(meta["active"])
        self.assertLessEqual(abs(meta["home_delta"]),.75)
        self.assertLessEqual(abs(meta["away_delta"]),.75)
        self.assertAlmostEqual(h,5.0+meta["home_delta"])
        self.assertAlmostEqual(a,4.0+meta["away_delta"])

    def test_inactive_artifact_is_identity(self):
        h,a,meta=runtime.apply_pair(5.0,4.0,"FINAL",{"active":False,"phase_scope":"FINAL"})
        self.assertEqual((h,a),(5.0,4.0))
        self.assertFalse(meta["active"])


if __name__ == "__main__":
    unittest.main()
