from __future__ import annotations

import unittest


class V1352RuntimeHookTests(unittest.TestCase):
    def test_v13_uses_explicit_engine_without_global_engine_monkeypatches(self):
        # Importing v13_entry installs V12.3 compatibility first, then assigns an
        # explicit V13Engine instance to runner.engine.
        from v11 import v13_entry  # noqa: F401
        from v11 import engine_v12, methodology_v123, runner, v13_runtime
        from v11.v13_engine import V13Engine

        status = v13_runtime.assert_runtime_hooks()
        self.assertTrue(status["installed"])
        self.assertTrue(status["explicit_engine"])
        self.assertTrue(status["no_v13_engine_global_monkeypatches"])
        self.assertIsInstance(runner.engine, V13Engine)
        self.assertFalse(getattr(engine_v12.analyze, "_v13_runtime_hook", False))
        self.assertFalse(getattr(engine_v12._analysis_points, "_v13_runtime_hook", False))
        self.assertFalse(getattr(engine_v12.prob_home_win, "_v13_runtime_hook", False))
        self.assertFalse(getattr(methodology_v123.bootstrap_prior_v123, "_v13_runtime_hook", False))

    def test_explicit_engine_builds_same_validation_baseline_metadata(self):
        # This test can run first alphabetically in a fresh unittest process.
        # Initialize the same V12.3 compatibility layer that production V13.10
        # installs through v13_entry before exercising the explicit engine.
        from v11 import v13_entry  # noqa: F401
        from v11 import probability_contract_v13 as contract
        from v11.v13_engine import V13Engine

        values = V13Engine._validated_historical_priors(
            5.0,
            4.0,
            {"active": False, "phase_models": {}},
            "EARLY",
        )
        self.assertEqual(len(values), 8)
        meta = values[2]
        self.assertEqual(meta.get("v13_validation_baseline_home_mu"), values[0])
        self.assertEqual(meta.get("v13_validation_baseline_away_mu"), values[1])
        self.assertEqual(meta.get("v13_validation_baseline_dispersion"), values[4])
        self.assertEqual(meta.get("v13_validation_baseline_environment_sigma"), values[6])
        self.assertEqual(meta.get("v13_validation_model_generation"), contract.MODEL_GENERATION_FINGERPRINT)
        self.assertEqual(meta.get("v13_validation_baseline_source"), "v123-compose-runtime-pre-v13-candidate")

    def test_runtime_persists_explicit_validation_baseline_metadata(self):
        from pathlib import Path

        runtime = Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        engine = Path("v11/v13_engine.py").read_text(encoding="utf-8")
        self.assertIn('payload["v13_validation_baseline"]', runtime)
        self.assertIn('result["v13_validation_baseline"]', engine)
        self.assertIn('runner.engine = engine', runtime)
        self.assertIn('"global_engine_monkeypatches_required": False', engine)
        self.assertNotIn('methodology_v123.bootstrap_prior_v123 = validated_historical_priors', runtime)
        self.assertNotIn('engine_v12._analysis_points = v13_analysis_points', runtime)


if __name__ == "__main__":
    unittest.main()
