from __future__ import annotations

import unittest
from unittest.mock import patch

from v11.pipeline_v13 import ProbabilityPipelineV13
from v11.v13_engine import V13Engine


class V139ExplicitEngineTests(unittest.TestCase):
    def _result(self):
        return {
            "phase": "FINAL",
            "as_of": "2026-08-19T17:00:00+00:00",
            "structural_hmu": 4.8,
            "structural_amu": 4.2,
            "hmu": 4.8,
            "amu": 4.2,
            "quality": 0.8,
            "ctx": {"home": "Home Club", "away": "Away Club"},
            "features": {"run_dispersion": 3.0, "run_environment_sigma": 0.08},
            "canonical_lines": {"RUNLINE": None, "TOTAL": None},
            "event": {"bookmakers": []},
            "options": [],
            "data_quality": {"score": 0.9, "model_input_score": 0.9},
        }

    def test_standard_runline_surface_contains_both_pairs(self):
        engine = V13Engine(base_analyze=lambda *args, **kwargs: self._result())
        result = self._result()
        with patch("v11.v13_engine.market.sharp_consensus", return_value={"p": None, "n": 0, "books": []}), \
             patch("v11.v13_engine.core.winamax_price", return_value=None), \
             patch("v11.v13_engine.pro_model.load_model", return_value={"active": False}), \
             patch("v11.v13_engine.pro_model.model_uncertainty", return_value=0.05):
            engine._ensure_standard_runlines(result)
        keys = {(o["name"], o["point"]) for o in result["options"]}
        self.assertEqual(
            keys,
            {
                ("Home Club", -1.5),
                ("Away Club", 1.5),
                ("Home Club", 1.5),
                ("Away Club", -1.5),
            },
        )
        self.assertTrue(all(o["line_source"] == "v13-standard-1.5" for o in result["options"]))
        self.assertTrue(all(o["execution_available"] is False for o in result["options"]))

    def test_identity_calibration_keeps_market_out_of_primary_probability(self):
        calibration = {
            "schema": "v13-baseball-calibration-model-v2",
            "baseball_only": True,
            "calibrators": {},
        }
        pipeline = ProbabilityPipelineV13(calibration, {})
        engine = V13Engine(base_analyze=lambda *args, **kwargs: self._result(), pipeline=pipeline)
        result = self._result()
        result["options"] = [
            {
                "market": "ML",
                "name": "Home Club",
                "p_structural": 0.61,
                "p_learned": 0.61,
                "p_market": 0.35,
                "p_push": 0.0,
                "p_push_model": 0.0,
                "sharp_dispersion": 0.02,
            }
        ]
        out = engine._apply_probability_contract(result)
        option = out["options"][0]
        self.assertAlmostEqual(option["p_baseball_raw"], 0.61)
        self.assertAlmostEqual(option["p_baseball_calibrated"], 0.61)
        self.assertAlmostEqual(option["p_predictive_final"], 0.61)
        self.assertEqual(option["p_market"], 0.35)
        self.assertFalse(option["posterior_allowed_for_edge"])
        self.assertEqual(option["edge_probability_field"], "p_baseball_calibrated")

    def test_runtime_install_does_not_mark_v12_engine_as_v13_hooked(self):
        from v11 import engine_v12, methodology_v123, v13_entry, v13_runtime  # noqa: F401

        status = v13_runtime.assert_runtime_hooks()
        self.assertTrue(status["explicit_engine"])
        self.assertTrue(status["no_v13_engine_global_monkeypatches"])
        self.assertFalse(getattr(engine_v12.analyze, "_v13_runtime_hook", False))
        self.assertFalse(getattr(engine_v12._analysis_points, "_v13_runtime_hook", False))
        self.assertFalse(getattr(engine_v12.prob_home_win, "_v13_runtime_hook", False))
        self.assertFalse(getattr(methodology_v123.bootstrap_prior_v123, "_v13_runtime_hook", False))


if __name__ == "__main__":
    unittest.main()
