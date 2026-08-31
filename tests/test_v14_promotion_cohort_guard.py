from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.promotion_guard import PROMOTION_COHORT_POLICY, build as build_guard
from v14.research_registry import register


NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


class V14PromotionCohortGuardTests(unittest.TestCase):
    def _registration(self, registry: Path) -> dict:
        spec = {
            "experiment_id": "TEST-PROMO-01",
            "hypothesis": "strict scheduled final promotion test",
            "model": "test.model",
            "features": ["x"],
            "training_period": "development",
            "validation_period": "post-registration prospective",
            "primary_metric": "paired metric",
            "success_rule": "locked rule",
            "code_commit_sha": "0123456789abcdef",
        }
        return register(spec, registry, registered_at=NOW.isoformat())

    def _artifact(self, registration: dict, **overrides) -> dict:
        evidence = {
            "prospective_only": True,
            "experiment_id": registration["experiment_id"],
            "model_generation": MODEL_GENERATION,
            "probability_policy_id": PROBABILITY_POLICY_ID,
            "phase": "FINAL",
            "run_trigger": "SCHEDULED_FINAL",
            "cohort_policy": PROMOTION_COHORT_POLICY,
            "registration_timestamp": registration["registered_at"],
            "first_observation_at": (NOW + timedelta(minutes=1)).isoformat(),
            "latest_observation_at": (NOW + timedelta(days=5)).isoformat(),
            "eligible_observations": 20,
            "code_commit_sha": registration["code_commit_sha"],
            "success_rule_locked": True,
        }
        evidence.update(overrides)
        return {
            "schema": "test-challenger-v1",
            "status": "PROMOTION_CANDIDATE",
            "promotion_evidence": evidence,
        }

    def test_strict_scheduled_final_current_policy_evidence_can_pass_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry.jsonl"
            artifact_path = root / "artifact.json"
            registration = self._registration(registry)
            artifact_path.write_text(json.dumps(self._artifact(registration)), encoding="utf-8")
            out = build_guard(registry=registry, artifact_paths={str(artifact_path): registration["experiment_id"]})
            self.assertTrue(out["valid"])
            self.assertEqual(out["schema"], "pulsar-v14-promotion-guard-v2")
            self.assertEqual(out["promotion_cohort_policy"], PROMOTION_COHORT_POLICY)
            self.assertTrue(out["artifacts"][str(artifact_path)]["promotion_authorized"])

    def test_manual_or_wrong_policy_promotion_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry.jsonl"
            artifact_path = root / "artifact.json"
            registration = self._registration(registry)
            artifact = self._artifact(
                registration,
                run_trigger="MANUAL",
                probability_policy_id="other-policy",
                cohort_policy="GENERIC_POST_REGISTRATION",
            )
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            out = build_guard(registry=registry, artifact_paths={str(artifact_path): registration["experiment_id"]})
            self.assertFalse(out["valid"])
            failures = out["unsafe_promotion_claims"][0]["failures"]
            self.assertIn("promotion_run_trigger_must_be_scheduled_final", failures)
            self.assertIn("promotion_probability_policy_mismatch", failures)
            self.assertIn("promotion_cohort_policy_mismatch", failures)


if __name__ == "__main__":
    unittest.main()
