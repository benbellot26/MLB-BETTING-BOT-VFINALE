from __future__ import annotations

import unittest

from v11 import professional_probability_checks_v13 as checks
from v11 import v13_probability_surface as surface


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

    @staticmethod
    def _complete_ml_runline_surface():
        def opt(market, name, p, point=None):
            return {"market": market, "name": name, "point": point, "p_baseball_calibrated": p}

        return {
            "ctx": {"home": "Home", "away": "Away"},
            "canonical_lines": {"RUNLINE": -1.5, "TOTAL": None},
            "analysis_lines": {"RUNLINE": {"points": [-1.5, 1.5]}, "TOTAL": {"points": [], "source": "none"}},
            "options": [
                opt("ML", "Home", .55),
                opt("ML", "Away", .45),
                opt("RUNLINE", "Home", .65, 1.5),
                opt("RUNLINE", "Away", .35, -1.5),
                opt("RUNLINE", "Home", .45, -1.5),
                opt("RUNLINE", "Away", .55, 1.5),
            ],
        }

    def test_unavailable_total_market_does_not_invalidate_surface(self):
        result = self._complete_ml_runline_surface()
        report = surface.validate(result, require_display_surface=True)
        self.assertTrue(report["valid"], report)
        self.assertTrue(report["display_complete"], report)
        self.assertFalse(report["total_market_expected"])
        self.assertFalse(report["total_market_available"])
        self.assertNotIn("canonical_total_pair_missing", report["errors"])

    def test_expected_but_partial_total_market_still_fails_closed(self):
        result = self._complete_ml_runline_surface()
        result["canonical_lines"]["TOTAL"] = 8.5
        result["analysis_lines"]["TOTAL"] = {"points": [8.5], "source": "winamax"}
        result["options"].append({
            "market": "TOTAL", "name": "Over", "point": 8.5, "p_baseball_calibrated": .52,
        })
        report = surface.validate(result, require_display_surface=True)
        self.assertFalse(report["valid"])
        self.assertTrue(report["total_market_expected"])
        self.assertTrue(report["total_market_available"])
        self.assertIn("canonical_total_pair_missing", report["errors"])
        self.assertIn("display_surface_incomplete", report["errors"])


if __name__ == "__main__":
    unittest.main()
