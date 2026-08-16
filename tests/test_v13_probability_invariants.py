from __future__ import annotations

import unittest

from v11 import professional_probability_checks_v13 as checks


class ProbabilityInvariantTests(unittest.TestCase):
    def test_valid_v13_option_passes(self):
        result = {
            "market_blend_allowed_for_edge":False,
            "options":[{
                "market":"ML","name":"A",
                "p_baseball_raw":.60,
                "p_baseball_calibrated":.58,
                "p_effective":.58,
                "probability_product":"calibrated-baseball-only",
                "baseball_probability_source":"baseball-only-score-distribution",
            }],
        }
        self.assertTrue(checks.check_result(result)["passes"])

    def test_legacy_market_blend_alias_fails(self):
        result = {
            "market_blend_allowed_for_edge":False,
            "options":[{
                "p_baseball_raw":.60,"p_baseball_calibrated":.58,"p_effective":.55,
                "probability_product":"calibrated-baseball-only",
                "baseball_probability_source":"baseball-only-score-distribution",
            }],
        }
        self.assertFalse(checks.check_result(result)["passes"])


if __name__ == "__main__":
    unittest.main()
