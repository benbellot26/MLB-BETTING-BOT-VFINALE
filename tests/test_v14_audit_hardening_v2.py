from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.api_budget import record_prediction_snapshot
from v14.certification_timing import CERTIFICATION_RUN_TRIGGER
from v14.decision import evaluate as decision_status
from v14.paper_ledger import PRIMARY_SHARP_BENCHMARK, report as paper_report
from v14.promotion_guard import PROMOTION_COHORT_POLICY, build as promotion_guard
from v14.research_registry import register
from v14.scheduled_prediction_gate import build as scheduled_prediction_gate


class V14AuditHardeningV2Tests(unittest.TestCase):
    def _decision_inputs(self, *, phase="FINAL", consensus=.60, pinnacle=.60, analyzed_at="2026-08-31T19:30:00Z"):
        prediction={
            "phase":phase,
            "game_date":"2026-08-31T20:00:00Z",
            "analyzed_at":analyzed_at,
            "probabilities":{"home_ml":.70,"away_ml":.30},
            "probability_intervals":{"selections":{"home_ml":{"lower":.66,"half_width_pp":4.0}}},
            "calibration":{"markets":{"ML":{"accepted":True}}},
        }
        market={"freshness_verified":True,"commence_time":"2026-08-31T20:00:00Z","markets":{"ML":{"selections":{"home":{"price":1.80}}}}}
        sharp={"freshness_verified":True,"selections":{"home_ml":{"fair_probability":consensus,"source_count":2,"sportsbook_source_count":2,"exchange_proxy_source_count":0,"contributors":[{"bookmaker":"pinnacle","source_type":"SPORTSBOOK","fair_probability":pinnacle},{"bookmaker":"betonlineag","source_type":"SPORTSBOOK","fair_probability":consensus}]}}}
        certification={"certified":True,"markets":{"ML":{"betting_certified":True}}}
        return prediction,market,sharp,certification

    def test_certified_bet_requires_final_phase(self):
        prediction,market,sharp,certification=self._decision_inputs(phase="EARLY")
        out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=certification)
        self.assertEqual(out["best"]["status"],"RESEARCH_ONLY")
        self.assertTrue(out["best"]["research_ready"])
        self.assertIn("betting_phase_not_final",out["best"]["blockers"])
        self.assertFalse(out["recommendations_authorized"])

    def test_final_certified_bet_requires_and_uses_pinnacle_primary_edge(self):
        prediction,market,sharp,certification=self._decision_inputs()
        out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=certification)
        best=out["best"]
        self.assertEqual(best["status"],"BET")
        self.assertTrue(best["betting_timing_ok"])
        self.assertAlmostEqual(best["minutes_to_game"],30.0)
        self.assertEqual(best["primary_sharp_benchmark"],"PINNACLE_NO_VIG")
        self.assertAlmostEqual(best["pinnacle_probability"],.60)
        self.assertGreater(best["robust_primary_sharp_edge_pp"],0)
        self.assertTrue(best["primary_edge_qualified"])

    def test_final_outside_certified_timing_window_is_research_only(self):
        prediction,market,sharp,certification=self._decision_inputs(analyzed_at="2026-08-31T18:30:00Z")
        out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=certification)
        best=out["best"]
        self.assertTrue(best["research_ready"])
        self.assertFalse(best["betting_timing_ok"])
        self.assertAlmostEqual(best["minutes_to_game"],90.0)
        self.assertEqual(best["status"],"RESEARCH_ONLY")
        self.assertIn("betting_timing_outside_certified_window",best["blockers"])
        self.assertFalse(out["recommendations_authorized"])

    def test_consensus_edge_cannot_override_negative_pinnacle_edge(self):
        prediction,market,sharp,certification=self._decision_inputs(consensus=.55,pinnacle=.68)
        out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=certification)
        best=out["best"]
        self.assertTrue(best["research_ready"])
        self.assertGreater(best["robust_sharp_edge_pp"],0)
        self.assertLess(best["robust_primary_sharp_edge_pp"],0)
        self.assertEqual(best["status"],"RESEARCH_ONLY")
        self.assertIn("pinnacle_primary_edge_not_qualified",best["blockers"])

    def test_missing_pinnacle_fails_closed_for_bet_but_preserves_research(self):
        prediction,market,sharp,certification=self._decision_inputs()
        sharp["selections"]["home_ml"]["contributors"]=[{"bookmaker":"betonlineag","source_type":"SPORTSBOOK","fair_probability":.60}]
        out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=certification)
        self.assertEqual(out["best"]["status"],"RESEARCH_ONLY")
        self.assertTrue(out["best"]["research_ready"])
        self.assertIn("pinnacle_primary_sharp_missing_for_bet",out["best"]["blockers"])

    def test_legacy_consensus_clv_cannot_be_reinterpreted_as_pinnacle_certification(self):
        row={
            "schema":"pulsar-v14-paper-bet-v7","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,
            "odds_event_time_verified":True,"game_pk":"1","canonical_market":"ML","analyzed_at":"2026-08-31T19:30:00Z","game_date":"2026-08-31T20:00:00Z",
            "close_quality":"CERTIFIED_CLOSE","close_captured_at":"2026-08-31T19:50:00Z","certification_clv_pp":1.25,
        }
        out=paper_report([row])
        self.assertEqual(out["certification_clv"]["n"],0)
        self.assertIsNone(out["latest_certified_close_at"])
        self.assertEqual(out["primary_clv_benchmark"],PRIMARY_SHARP_BENCHMARK)
        self.assertFalse(out["legacy_consensus_certification_clv_can_certify"])

    def test_only_explicit_scheduled_final_pinnacle_clv_counts_as_primary_certification_evidence(self):
        row={
            "schema":"pulsar-v14-paper-bet-v8","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,
            "run_trigger":CERTIFICATION_RUN_TRIGGER,"phase":"FINAL","odds_event_time_verified":True,"game_pk":"1","canonical_market":"ML","analyzed_at":"2026-08-31T19:30:00Z","game_date":"2026-08-31T20:00:00Z",
            "close_quality":"CERTIFIED_CLOSE","close_captured_at":"2026-08-31T19:50:00Z","certification_clv_pp":1.25,"certification_clv_benchmark":PRIMARY_SHARP_BENCHMARK,
        }
        out=paper_report([row])
        self.assertEqual(out["certification_clv"]["n"],1)
        self.assertEqual(out["certification_clv"]["benchmark"],PRIMARY_SHARP_BENCHMARK)
        self.assertEqual(out["latest_certified_close_at"],"2026-08-31T19:50:00Z")
        self.assertEqual(out["certification_entry_phase"],"FINAL")
        self.assertEqual(out["certification_run_trigger"],CERTIFICATION_RUN_TRIGGER)

    def test_manual_final_pinnacle_clv_is_excluded_from_certification_evidence(self):
        row={
            "schema":"pulsar-v14-paper-bet-v8","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,
            "run_trigger":"MANUAL","phase":"FINAL","odds_event_time_verified":True,"game_pk":"1","canonical_market":"ML","analyzed_at":"2026-08-31T19:30:00Z","game_date":"2026-08-31T20:00:00Z",
            "close_quality":"CERTIFIED_CLOSE","close_captured_at":"2026-08-31T19:50:00Z","certification_clv_pp":1.25,"certification_clv_benchmark":PRIMARY_SHARP_BENCHMARK,
        }
        out=paper_report([row])
        self.assertEqual(out["certification_clv"]["n"],0)
        self.assertEqual(out["excluded_non_scheduled_final_rows"],1)
        self.assertIsNone(out["latest_certified_close_at"])

    def test_early_pinnacle_clv_is_excluded_from_final_certification_evidence(self):
        row={
            "schema":"pulsar-v14-paper-bet-v8","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,
            "run_trigger":CERTIFICATION_RUN_TRIGGER,"phase":"EARLY","odds_event_time_verified":True,"game_pk":"1","canonical_market":"ML","analyzed_at":"2026-08-31T19:30:00Z","game_date":"2026-08-31T20:00:00Z",
            "close_quality":"CERTIFIED_CLOSE","close_captured_at":"2026-08-31T19:50:00Z","certification_clv_pp":1.25,"certification_clv_benchmark":PRIMARY_SHARP_BENCHMARK,
        }
        out=paper_report([row])
        self.assertEqual(out["certification_clv"]["n"],0)
        self.assertEqual(out["excluded_non_final_rows"],1)
        self.assertIsNone(out["latest_certified_close_at"])

    def test_scheduled_final_gate_ignores_manual_snapshot_and_stops_after_objective_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); predictions=root/"predictions.jsonl"; api_usage=root/"api.jsonl"
            now=datetime(2026,8,31,19,30,tzinfo=timezone.utc); game_time=now+timedelta(minutes=30)
            game={"gamePk":123,"gameDate":game_time.isoformat(),"status":{"abstractGameState":"Preview"},"teams":{"home":{"team":{"name":"Home"}},"away":{"team":{"name":"Away"}}}}
            loader=lambda day:[game]
            first=scheduled_prediction_gate(predictions_path=predictions,api_usage_path=api_usage,target_date="2026-08-31",now=now,games_loader=loader)
            self.assertTrue(first["run_required"])
            self.assertEqual(first["reason"],"FINAL_SNAPSHOT_DUE")
            self.assertEqual(first["due_game_ids"],["123"])

            manual={"model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"run_trigger":"MANUAL","game_pk":"123","game_date":game_time.isoformat(),"analyzed_at":now.isoformat(),"phase":"FINAL"}
            predictions.write_text(json.dumps(manual)+"\n",encoding="utf-8")
            still_due=scheduled_prediction_gate(predictions_path=predictions,api_usage_path=api_usage,target_date="2026-08-31",now=now,games_loader=loader)
            self.assertTrue(still_due["run_required"])

            scheduled=dict(manual);scheduled["run_trigger"]=CERTIFICATION_RUN_TRIGGER
            predictions.write_text(json.dumps(manual)+"\n"+json.dumps(scheduled)+"\n",encoding="utf-8")
            covered=scheduled_prediction_gate(predictions_path=predictions,api_usage_path=api_usage,target_date="2026-08-31",now=now,games_loader=loader)
            self.assertFalse(covered["run_required"])
            self.assertEqual(covered["reason"],"NO_FINAL_SNAPSHOT_DUE")

    def test_scheduled_final_gate_respects_persisted_paid_retry_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); predictions=root/"predictions.jsonl"; api_usage=root/"api.jsonl"
            now=datetime(2026,8,31,19,30,tzinfo=timezone.utc); game_time=now+timedelta(minutes=30)
            game={"gamePk":123,"gameDate":game_time.isoformat(),"status":{"abstractGameState":"Preview"},"teams":{}}
            record_prediction_snapshot(api_usage,now=now,due_games=["123"])
            out=scheduled_prediction_gate(predictions_path=predictions,api_usage_path=api_usage,target_date="2026-08-31",now=now+timedelta(minutes=5),games_loader=lambda day:[game])
            self.assertFalse(out["run_required"])
            self.assertEqual(out["reason"],"PREDICTION_RETRY_COOLDOWN")
            self.assertGreater(out["cooldown_remaining_minutes"],0)

    def _experiment_spec(self):
        return {
            "experiment_id":"TEST-EXP-01","hypothesis":"test","model":"v14.test","features":["x"],
            "training_period":"development","validation_period":"post-registration","primary_metric":"brier",
            "success_rule":"ci lower > 0","code_commit_sha":"abc123","multiplicity_family":"TEST",
        }

    def test_promotion_guard_blocks_legacy_promotion_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry=Path(tmp)/"registry.jsonl"; artifact=Path(tmp)/"candidate.json"
            register(self._experiment_spec(),registry,registered_at="2026-08-31T10:00:00Z")
            artifact.write_text(json.dumps({"status":"PROMOTION_ELIGIBLE"}),encoding="utf-8")
            out=promotion_guard(registry=registry,artifact_paths={str(artifact):"TEST-EXP-01"})
            self.assertFalse(out["valid"])
            self.assertEqual(len(out["unsafe_promotion_claims"]),1)
            self.assertIn("prospective_only_evidence_required",out["unsafe_promotion_claims"][0]["failures"])

    def test_promotion_guard_blocks_unregistered_promotion_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry=Path(tmp)/"registry.jsonl"; artifact=Path(tmp)/"legacy-live.json"
            artifact.write_text(json.dumps({"status":"PROMOTION_REVIEW","role":"PROMOTION_EVIDENCE_ONLY"}),encoding="utf-8")
            out=promotion_guard(registry=registry,artifact_paths={str(artifact):"UNREGISTERED-LEGACY-LIVE"})
            self.assertFalse(out["valid"])
            self.assertEqual(len(out["unsafe_promotion_claims"]),1)
            self.assertIn("experiment_not_preregistered",out["unsafe_promotion_claims"][0]["failures"])

    def test_promotion_guard_accepts_exact_post_registration_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry=Path(tmp)/"registry.jsonl"; artifact=Path(tmp)/"candidate.json"
            register(self._experiment_spec(),registry,registered_at="2026-08-31T10:00:00Z")
            artifact.write_text(json.dumps({
                "status":"PROSPECTIVE_PROMOTION_ELIGIBLE",
                "promotion_evidence":{
                    "prospective_only":True,
                    "experiment_id":"TEST-EXP-01",
                    "model_generation":MODEL_GENERATION,
                    "probability_policy_id":PROBABILITY_POLICY_ID,
                    "phase":"FINAL",
                    "run_trigger":CERTIFICATION_RUN_TRIGGER,
                    "cohort_policy":PROMOTION_COHORT_POLICY,
                    "registration_timestamp":"2026-08-31T10:00:00Z",
                    "first_observation_at":"2026-08-31T10:01:00Z","latest_observation_at":"2026-09-30T10:00:00Z",
                    "eligible_observations":400,"code_commit_sha":"abc123","success_rule_locked":True,
                },
            }),encoding="utf-8")
            out=promotion_guard(registry=registry,artifact_paths={str(artifact):"TEST-EXP-01"})
            self.assertTrue(out["valid"])
            self.assertTrue(out["artifacts"][str(artifact)]["promotion_authorized"])


if __name__=="__main__": unittest.main()
