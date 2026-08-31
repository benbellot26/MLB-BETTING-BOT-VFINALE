import unittest

from v14 import MODEL_GENERATION
from v14.coverage_ledger import LEGACY_GENERATION, LEGACY_TRIGGER, report, rows_from_candidate


def _result(*, game_pk="1", analyzed_at="2026-08-31T14:00:00+00:00", trigger="SCHEDULED_FINAL", phase="FINAL", market_fresh=True, sharp_fresh=True, execution_fresh=True):
    return {
        "model_generation": MODEL_GENERATION,
        "game_pk": game_pk,
        "game_date": "2026-08-31T14:30:00+00:00",
        "analyzed_at": analyzed_at,
        "run_trigger": trigger,
        "phase": phase,
        "home": "Home",
        "away": "Away",
        "market_snapshot": {"freshness_verified": market_fresh},
        "sharp_market": {"freshness_verified": sharp_fresh, "selections": {"home_ml": {"fair_probability": .55}}},
        "execution_market": {"freshness_verified": execution_fresh, "selections": {"home_ml": {"price": 1.90}}},
    }


def _coverage_row(*, game_pk="1", analyzed_at="2026-08-31T14:00:00+00:00", trigger="SCHEDULED_FINAL", phase="FINAL", predicted=True, observable=True, reason=None, generation=MODEL_GENERATION):
    return {
        "schema": "pulsar-v14-coverage-record-v1",
        "model_generation": generation,
        "target_date": "2026-08-31",
        "analyzed_at": analyzed_at,
        "game_pk": game_pk,
        "run_trigger": trigger,
        "phase": phase,
        "prediction_generated": predicted,
        "market_fresh": observable,
        "sharp_available": observable,
        "execution_available": observable,
        "fully_market_observable": observable,
        "eligible": predicted,
        "rejection_reason": reason,
    }


class V14CoverageCohortTests(unittest.TestCase):
    def test_execution_requires_explicit_verified_freshness(self):
        candidate = {
            "model_generation": MODEL_GENERATION,
            "target_date": "2026-08-31",
            "analyzed_at": "2026-08-31T14:00:00+00:00",
            "run_trigger": "SCHEDULED_FINAL",
            "results": [_result(execution_fresh=None)],
            "skipped": [],
        }
        row = rows_from_candidate(candidate)[0]
        self.assertEqual(row["model_generation"], MODEL_GENERATION)
        self.assertFalse(row["execution_available"])
        self.assertFalse(row["fully_market_observable"])

    def test_manual_and_scheduled_final_are_reported_separately(self):
        rows = [
            _coverage_row(trigger="MANUAL", analyzed_at="2026-08-31T13:00:00+00:00"),
            _coverage_row(trigger="SCHEDULED_FINAL", analyzed_at="2026-08-31T14:00:00+00:00"),
        ]
        out = report(rows)
        self.assertEqual(out["observations"], 2)
        self.assertEqual(out["first_observation_unique_games"]["observations"], 1)
        self.assertEqual(out["by_run_trigger"]["MANUAL"]["first_observation_unique_games"]["observations"], 1)
        self.assertEqual(out["by_run_trigger"]["SCHEDULED_FINAL"]["first_observation_unique_games"]["observations"], 1)
        self.assertEqual(out["scheduled_final_trigger"]["first_observation_unique_games"]["observations"], 1)

    def test_later_success_cannot_hide_first_scheduled_failure(self):
        rows = [
            _coverage_row(
                analyzed_at="2026-08-31T14:00:00+00:00",
                trigger="SCHEDULED_FINAL",
                predicted=False,
                observable=False,
                reason="FINAL snapshot requires both confirmed 9/9 lineups",
            ),
            _coverage_row(
                analyzed_at="2026-08-31T14:10:00+00:00",
                trigger="SCHEDULED_FINAL",
                predicted=True,
                observable=True,
            ),
        ]
        out = report(rows)
        scheduled = out["scheduled_final_trigger"]
        self.assertEqual(scheduled["raw"]["observations"], 2)
        self.assertEqual(scheduled["raw"]["predicted"], 1)
        canonical = scheduled["first_observation_unique_games"]
        self.assertEqual(canonical["observations"], 1)
        self.assertEqual(canonical["predicted"], 0)
        self.assertEqual(canonical["fully_market_observable"], 0)
        self.assertEqual(canonical["rejection_reasons"], {"FINAL snapshot requires both confirmed 9/9 lineups": 1})

    def test_skipped_row_inherits_candidate_run_trigger_and_generation(self):
        candidate = {
            "model_generation": MODEL_GENERATION,
            "target_date": "2026-08-31",
            "analyzed_at": "2026-08-31T14:00:00+00:00",
            "run_trigger": "SCHEDULED_FINAL",
            "results": [],
            "skipped": [{"game_pk": "2", "reason": "odds_event_unmatched"}],
        }
        row = rows_from_candidate(candidate)[0]
        self.assertEqual(row["model_generation"], MODEL_GENERATION)
        self.assertEqual(row["run_trigger"], "SCHEDULED_FINAL")
        self.assertFalse(row["odds_matched"])
        self.assertFalse(row["eligible"])

    def test_missing_legacy_trigger_is_never_silently_called_manual_or_scheduled(self):
        out = report([_coverage_row(trigger=None)])
        self.assertIn(LEGACY_TRIGGER, out["by_run_trigger"])
        self.assertNotIn("MANUAL", out["by_run_trigger"])
        self.assertNotIn("SCHEDULED_FINAL", out["by_run_trigger"])

    def test_phase_view_keeps_unknown_skips_visible(self):
        rows = [
            _coverage_row(game_pk="1", phase="FINAL"),
            _coverage_row(game_pk="2", phase=None, predicted=False, observable=False, reason="input_failure"),
        ]
        out = report(rows)
        self.assertEqual(out["by_phase"]["FINAL"]["raw"]["observations"], 1)
        self.assertEqual(out["by_phase"]["UNKNOWN"]["raw"]["observations"], 1)
        self.assertEqual(out["by_phase"]["UNKNOWN"]["first_observation_unique_games"]["rejection_reasons"], {"input_failure": 1})

    def test_other_or_missing_generations_cannot_pollute_current_coverage(self):
        rows = [
            _coverage_row(game_pk="1", generation=MODEL_GENERATION),
            _coverage_row(game_pk="2", generation="old-generation"),
            _coverage_row(game_pk="3", generation=None),
        ]
        out = report(rows)
        self.assertEqual(out["observations"], 1)
        self.assertEqual(out["excluded_other_generation_observations"], 2)
        self.assertEqual(out["raw_observations_by_model_generation"][MODEL_GENERATION], 1)
        self.assertEqual(out["raw_observations_by_model_generation"]["old-generation"], 1)
        self.assertEqual(out["raw_observations_by_model_generation"][LEGACY_GENERATION], 1)


if __name__ == "__main__":
    unittest.main()
