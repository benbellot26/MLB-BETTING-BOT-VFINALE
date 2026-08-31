from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.decision import evaluate as evaluate_decision
from v14.prospective_cohort import build as build_prospective_cohort
from v14.research_registry import register


NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def _decision_inputs(*, certified: bool) -> dict:
    analyzed_at = NOW.isoformat()
    game_date = (NOW + timedelta(minutes=30)).isoformat()
    prediction = {
        "phase": "FINAL",
        "analyzed_at": analyzed_at,
        "game_date": game_date,
        "probabilities": {"home_ml": 0.70, "away_ml": 0.30},
        "probability_intervals": {
            "selections": {
                "home_ml": {"lower": 0.65, "half_width_pp": 5.0},
                "away_ml": {"lower": 0.25, "half_width_pp": 5.0},
            }
        },
        "calibration": {
            "markets": {
                "ML": {
                    "accepted": False,
                    "active": False,
                    "status": "COLLECTING",
                    "method": "identity",
                }
            }
        },
    }
    market_snapshot = {
        "freshness_verified": True,
        "commence_time": game_date,
        "markets": {},
    }
    sharp_market = {
        "freshness_verified": True,
        "selections": {
            "home_ml": {
                "fair_probability": 0.55,
                "source_count": 2,
                "sportsbook_source_count": 1,
                "exchange_proxy_source_count": 0,
                "dispersion_pp": 0.0,
                "range_pp": 0.0,
                "contributors": [
                    {
                        "bookmaker": "pinnacle",
                        "source_type": "SPORTSBOOK",
                        "fair_probability": 0.54,
                    }
                ],
            }
        },
    }
    execution_market = {
        "freshness_verified": True,
        "selections": {
            "home_ml": {"price": 2.0, "bookmaker": "winamax_fr"},
        },
    }
    certification = {
        "certified": certified,
        "markets": {"ML": {"betting_certified": certified}},
    }
    return {
        "prediction": prediction,
        "market_snapshot": market_snapshot,
        "sharp_market": sharp_market,
        "execution_market": execution_market,
        "certification": certification,
    }


class V14ShadowCalibrationDecisionTests(unittest.TestCase):
    def test_collecting_shadow_calibrator_does_not_block_paper_clv_candidate(self) -> None:
        out = evaluate_decision(**_decision_inputs(certified=False))
        row = next(r for r in out["candidates"] if r["selection"] == "home_ml")
        self.assertTrue(row["edge_qualified"])
        self.assertTrue(row["research_ready"])
        self.assertTrue(row["betting_edge_qualified"])
        self.assertFalse(row["shadow_calibration_accepted"])
        self.assertEqual(row["shadow_calibration_status"], "COLLECTING")
        self.assertEqual(row["shadow_calibration_role"], "DIAGNOSTIC_ONLY")
        self.assertNotIn("calibration_not_accepted", row["blockers"])
        self.assertEqual(row["status"], "RESEARCH_ONLY")

    def test_collecting_shadow_calibrator_cannot_veto_already_strictly_certified_bet(self) -> None:
        out = evaluate_decision(**_decision_inputs(certified=True))
        row = next(r for r in out["candidates"] if r["selection"] == "home_ml")
        self.assertTrue(row["research_ready"])
        self.assertTrue(row["market_betting_certified"])
        self.assertNotIn("calibration_not_accepted", row["blockers"])
        self.assertEqual(row["status"], "BET")
        self.assertTrue(out["recommendations_authorized"])
        self.assertFalse(out["shadow_calibration_can_block_decision"])


class V14ProspectiveCohortGateTests(unittest.TestCase):
    def _row(
        self,
        game_pk: str,
        analyzed_at: datetime,
        game_date: datetime,
        *,
        trigger: str = "SCHEDULED_FINAL",
        phase: str = "FINAL",
        policy: str = PROBABILITY_POLICY_ID,
        generation: str = MODEL_GENERATION,
        settled: bool = False,
    ) -> dict:
        return {
            "model_generation": generation,
            "probability_policy_id": policy,
            "run_trigger": trigger,
            "game_pk": game_pk,
            "analyzed_at": analyzed_at.isoformat(),
            "game_date": game_date.isoformat(),
            "phase": phase,
            "settled": settled,
        }

    def test_only_first_post_registration_scheduled_final_current_policy_snapshot_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            predictions = root / "predictions.jsonl"
            registry = root / "registry.jsonl"
            registered_at = NOW
            spec = {
                "experiment_id": "TEST-EXP-01",
                "hypothesis": "test strict prospective cohort",
                "model": "test.model",
                "features": ["x"],
                "training_period": "development",
                "validation_period": "post-registration",
                "primary_metric": "metric",
                "success_rule": "rule",
                "code_commit_sha": "0123456789abcdef",
            }
            register(spec, registry, registered_at=registered_at.isoformat())

            rows = [
                # Before registration: never eligible.
                self._row("pre", NOW - timedelta(minutes=10), NOW + timedelta(minutes=20)),
                # Current-policy post-registration rows that remain descriptive only.
                self._row("manual", NOW + timedelta(minutes=1), NOW + timedelta(minutes=31), trigger="MANUAL"),
                self._row("late", NOW + timedelta(minutes=2), NOW + timedelta(minutes=32), phase="LATE"),
                self._row("outside", NOW + timedelta(minutes=3), NOW + timedelta(minutes=93)),
                # First valid certification snapshot for game a.
                self._row("a", NOW + timedelta(minutes=4), NOW + timedelta(minutes=34)),
                # Later valid snapshot for the same game must not double count.
                self._row("a", NOW + timedelta(minutes=14), NOW + timedelta(minutes=34)),
                # Wrong probability policy must never enter promotion evidence.
                self._row("wrong-policy", NOW + timedelta(minutes=5), NOW + timedelta(minutes=35), policy="other-policy"),
                # A second independent valid game.
                self._row("b", NOW + timedelta(minutes=6), NOW + timedelta(minutes=36), settled=True),
            ]
            predictions.write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
                encoding="utf-8",
            )

            report = build_prospective_cohort(predictions, registry)
            exp = report["experiments"]["TEST-EXP-01"]
            self.assertEqual(report["schema"], "pulsar-v14-prospective-cohort-report-v2")
            self.assertEqual(report["promotion_cohort_policy"], "FIRST_SCHEDULED_FINAL_CURRENT_POLICY_PER_GAME")
            self.assertEqual(report["promotion_run_trigger"], "SCHEDULED_FINAL")
            self.assertEqual(report["promotion_phase"], "FINAL")
            self.assertEqual(exp["prospective_rows"], 2)
            self.assertEqual(exp["prospective_games"], 2)
            self.assertEqual(exp["settled_games"], 1)
            self.assertEqual(exp["phase_rows"], {"EARLY": 0, "LATE": 0, "FINAL": 2})
            self.assertGreater(exp["descriptive_post_registration_rows"], exp["prospective_rows"])
            self.assertEqual(exp["promotion_cohort_policy"], "FIRST_SCHEDULED_FINAL_CURRENT_POLICY_PER_GAME")
            self.assertEqual(exp["model_generation"], MODEL_GENERATION)
            self.assertEqual(exp["probability_policy_id"], PROBABILITY_POLICY_ID)


if __name__ == "__main__":
    unittest.main()
