import unittest

from v14.pick_tracking import load_pick_performance


class V14PickTrackingTests(unittest.TestCase):
    def test_august_25_reported_results_are_loaded_for_evaluation_only(self):
        report = load_pick_performance()
        self.assertEqual(report["role"], "evaluation_only")
        self.assertFalse(report["prediction_feature_usage"])
        self.assertEqual(report["overall"]["n"], 16)
        self.assertEqual(report["overall"]["wins"], 8)
        self.assertEqual(report["overall"]["losses"], 8)
        self.assertAlmostEqual(report["overall"]["hit_rate"], 0.5)
        self.assertEqual(report["by_market"]["TOTAL_OVER"]["n"], 10)
        self.assertEqual(report["by_market"]["TOTAL_OVER"]["wins"], 6)
        self.assertEqual(report["by_market"]["ML"]["n"], 6)
        self.assertEqual(report["by_market"]["ML"]["wins"], 2)
        self.assertEqual(report["overall"]["known_price_n"], 14)
        self.assertAlmostEqual(report["overall"]["flat_1u_profit_known_prices"], -1.21, places=8)


if __name__ == "__main__":
    unittest.main()
