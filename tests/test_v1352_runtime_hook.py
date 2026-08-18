from __future__ import annotations

import unittest


class V1352RuntimeHookTests(unittest.TestCase):
    def test_v13_hooks_the_bootstrap_function_used_by_project_v123(self):
        # Importing v13_entry installs the complete V12.3 -> V13 runtime chain.
        from v11 import v13_entry  # noqa: F401
        from v11 import engine_v12, methodology_v123
        from v11 import probability_contract_v13 as contract

        values = methodology_v123.bootstrap_prior_v123(
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

        # project_v123() resolves methodology_v123.bootstrap_prior_v123 through
        # compose_runtime(), while legacy callers may still use engine_v12.
        # Both must point to the same V13 wrapper.
        self.assertIs(engine_v12._bootstrap_prior, methodology_v123.bootstrap_prior_v123)

    def test_runtime_persists_explicit_validation_baseline_metadata(self):
        from pathlib import Path

        text = Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        self.assertIn('result["v13_validation_baseline"]', text)
        self.assertIn('payload["v13_validation_baseline"]', text)
        self.assertIn('methodology_v123.bootstrap_prior_v123 = validated_historical_priors', text)


if __name__ == "__main__":
    unittest.main()
