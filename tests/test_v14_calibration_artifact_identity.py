from __future__ import annotations

import copy
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.probability_calibration import calibrate_probability, calibrate_surface


class CalibrationArtifactIdentityTests(unittest.TestCase):
    def _artifact(self) -> dict:
        return {
            "schema": "pulsar-v14-calibration-v3",
            "model_generation": MODEL_GENERATION,
            "probability_policy_id": PROBABILITY_POLICY_ID,
            "generated_at": "2026-08-28T00:00:00+00:00",
            "latest_observation_at": "2026-08-27T23:00:00+00:00",
            "calibrators": {
                "MARKET:ML": {
                    "active": True,
                    "accepted": True,
                    "method": "platt-logit",
                    "n": 500,
                    "slope": 0.5,
                    "intercept": 0.1,
                    "status": "ACTIVE_TRANSFORM",
                }
            },
        }

    def test_exact_identity_injected_artifact_is_shadow_only_until_policy_promotion(self) -> None:
        surface, meta = calibrate_surface(
            {"home_ml": 0.60, "away_ml": 0.40},
            phase="EARLY",
            artifact=self._artifact(),
        )
        self.assertFalse(meta["any_active"])
        self.assertTrue(meta["any_research_candidate_active"])
        self.assertFalse(meta["production_transform_applied"])
        self.assertTrue(meta["all_accepted"])
        self.assertAlmostEqual(surface["home_ml"], 0.60)
        self.assertAlmostEqual(surface["away_ml"], 0.40)
        self.assertAlmostEqual(surface["home_ml"] + surface["away_ml"], 1.0)

    def test_injected_artifact_fails_closed_on_schema_generation_or_policy_mismatch(self) -> None:
        bad_artifacts = []
        for field, value in (
            ("schema", "pulsar-v14-calibration-v2"),
            ("model_generation", "stale-generation"),
            ("probability_policy_id", "stale-policy"),
        ):
            artifact = copy.deepcopy(self._artifact())
            artifact[field] = value
            bad_artifacts.append(artifact)
        missing_policy = copy.deepcopy(self._artifact())
        missing_policy.pop("probability_policy_id")
        bad_artifacts.append(missing_policy)

        for artifact in bad_artifacts:
            with self.subTest(identity=artifact):
                surface, meta = calibrate_surface(
                    {"home_ml": 0.60, "away_ml": 0.40},
                    phase="EARLY",
                    artifact=artifact,
                )
                self.assertFalse(meta["any_active"])
                self.assertFalse(meta["all_accepted"])
                self.assertAlmostEqual(surface["home_ml"], 0.60)
                self.assertAlmostEqual(surface["away_ml"], 0.40)
                self.assertEqual(meta["markets"]["ML"]["n"], 0)

    def test_direct_probability_api_also_fails_closed(self) -> None:
        artifact = self._artifact()
        artifact["probability_policy_id"] = "wrong-policy"
        calibrated, meta = calibrate_probability(0.60, "ML", "EARLY", artifact)
        self.assertAlmostEqual(calibrated, 0.60)
        self.assertFalse(meta["active"])
        self.assertFalse(meta["accepted"])
        self.assertEqual(meta["n"], 0)


if __name__ == "__main__":
    unittest.main()
