import unittest

from v14.parity_gate import ParityThresholds, assess_parity


class V14ParityGateTests(unittest.TestCase):
    def _candidate(self, scheduled=10, priced=10):
        return {"coverage": {"scheduled_future_games": scheduled, "priced_games": priced}}

    def _report(self, comparable=10, mean_delta=0.02, max_delta=0.08):
        return {
            "comparable_games": comparable,
            "mean_abs_structural_run_delta": mean_delta,
            "max_abs_structural_run_delta": max_delta,
        }

    def test_pass_is_evidence_only_and_never_authorizes_publication(self):
        assessment = assess_parity(self._candidate(), self._report())
        self.assertEqual(assessment["status"], "PASS")
        self.assertTrue(assessment["passed"])
        self.assertFalse(assessment["publication_authorized"])
        self.assertFalse(assessment["cutover_authorized"])

    def test_fails_when_coverage_is_too_low(self):
        assessment = assess_parity(self._candidate(scheduled=10, priced=8), self._report())
        self.assertEqual(assessment["status"], "FAIL")
        self.assertFalse(assessment["checks"]["candidate_coverage"])

    def test_fails_when_structural_delta_exceeds_limit(self):
        assessment = assess_parity(self._candidate(), self._report(max_delta=0.11))
        self.assertEqual(assessment["status"], "FAIL")
        self.assertFalse(assessment["checks"]["max_structural_delta"])

    def test_custom_thresholds_are_supported(self):
        thresholds = ParityThresholds(
            min_comparable_games=2,
            min_candidate_coverage=0.5,
            max_mean_abs_structural_run_delta=0.2,
            max_single_game_abs_structural_run_delta=0.4,
        )
        assessment = assess_parity(
            self._candidate(scheduled=4, priced=2),
            self._report(comparable=2, mean_delta=0.1, max_delta=0.3),
            thresholds=thresholds,
        )
        self.assertTrue(assessment["passed"])


if __name__ == "__main__":
    unittest.main()
