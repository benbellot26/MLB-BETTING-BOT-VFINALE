from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v11 import probability_contract_v13 as contract
from v11 import v13_daily_postmortem, v13_distribution_prior, v13_run_mean_runtime, v13_train


class V1352FinalHardeningTests(unittest.TestCase):
    def _row(self, *, game_pk=1, attach=True):
        row={
            "game_pk":game_pk,"phase":"FINAL",
            "analyzed_at":"2026-08-17T17:00:00+00:00","game_date":"2026-08-17T18:00:00+00:00",
            "home_score":5,"away_score":3,"home":"Home","away":"Away","features_from_postgame":False,
            "options":[{"market":"ML","name":"Home","is_canonical_line":True,"p_baseball_raw":.58,"result":"WIN"}],
        }
        if attach: contract.attach_contract(row)
        return row

    def _replay_row(self, *, game_pk=1, baseline=.55, attach=True):
        row=self._row(game_pk=game_pk,attach=attach)
        row.update({"point_in_time":True,"source_replay":f"replay-{game_pk}.json.gz",
                    "validation_baseline_model_generation":contract.MODEL_GENERATION_FINGERPRINT,
                    "calibration_evidence_candidate":True})
        row["options"][0]["p_replay_baseline_raw"]=baseline
        row["options"][0]["p_market"]=.54
        row["options"][0]["sharp_weight"]=.20
        return row

    def _distribution_artifact(self, generation="older-generation"):
        return {
            "schema":v13_distribution_prior.SCHEMA,
            "active":True,
            "historical_candidate_active":True,
            "phase_scope":"FINAL",
            "variant":"dispersion_only_2021_2026_walk_forward",
            "dispersion":2.835691107635618,
            "environment_sigma":.08,
            "market_data_used":False,
            "historical_odds_used":False,
            "historical_games":13104,
            "walk_forward":{"stable":True,"folds_total":5,"folds_passed":5},
            "model_generation":generation,
            "exact_final_games":60,
            "exact_transfer_required_games":60,
            "exact_transfer_status":"PASS_FINAL_ONLY",
            "exact_transfer_bootstrap":{"passes":True,"nll_gain_positive_probability":.95},
            "safety":{"exact_transfer_games_excluded_from_historical_fit":True},
        }

    def test_predictive_contract_requires_exact_model_generation(self):
        current=self._row()
        self.assertTrue(contract.row_is_predictively_compatible(current))
        stale=self._row(game_pk=2)
        stale["predictive_contract"]["model_generation"]="older-generation"
        self.assertFalse(contract.row_is_predictively_compatible(stale))
        self.assertIn("independent-transfer", contract.MODEL_GENERATION_FINGERPRINT)

    def test_exact_replay_marker_cannot_bypass_current_contract(self):
        exact=self._replay_row(attach=False)
        exact["v13_evidence_tier"]="A_EXACT_REPLAY"
        self.assertEqual(v13_train.eligible_probability_rows([exact]),[])
        self.assertEqual(v13_train.eligible_exact_replay_rows([exact]),[])

    def test_exact_replay_calibration_uses_only_pre_candidate_probability(self):
        exact=self._replay_row(baseline=.55)
        exact["options"][0]["p_baseball_raw"]=.91
        exact["options"][0]["p_baseball_calibrated"]=.88
        exact["options"][0]["p_posterior"]=.73
        rows=v13_train.eligible_exact_replay_rows([exact])
        self.assertEqual(len(rows),1)
        opt=rows[0]["options"][0]
        self.assertAlmostEqual(opt["p_baseball_raw"],.55)
        self.assertIsNone(opt.get("p_learned"))
        self.assertNotIn("p_market",opt)
        self.assertNotIn("p_posterior",opt)
        self.assertEqual(rows[0]["calibration_evidence_origin"],"exact-replay-pre-candidate-baseline")

    def test_native_current_row_wins_replay_collision(self):
        replay=v13_train.eligible_exact_replay_rows([self._replay_row(baseline=.55)])
        native=v13_train.eligible_probability_rows([self._row()])
        combined=v13_train.combine_calibration_rows(native,replay)
        self.assertEqual(len(combined),1)
        self.assertEqual(combined[0]["calibration_evidence_origin"],"native-current-generation")
        self.assertAlmostEqual(combined[0]["options"][0]["p_baseball_raw"],.58)

    def test_final_run_mean_prior_is_gated_until_native_transfer_passes(self):
        collecting={
            "schema":v13_run_mean_runtime.SCHEMA,
            "active":True,"historical_candidate_active":True,"phase_scope":"FINAL",
            "walk_forward":{"stable":True,"folds_total":4,"folds_passed":4},
            "model_generation":contract.MODEL_GENERATION_FINGERPRINT,
            "exact_final_games":59,"exact_transfer_required_games":60,"exact_transfer_status":"COLLECTING_FINAL_ONLY",
            "exact_transfer_bootstrap":{"passes":True,"nll_gain_positive_probability":.95},
            "safety":{"exact_transfer_games_excluded_from_historical_fit":True},
            "model":{"home_bias":.1,"away_bias":.1,"slope_delta":0,"max_adjustment":.15},
        }
        h,a,meta=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",collecting)
        self.assertEqual((h,a),(5.0,4.0)); self.assertFalse(meta["active"])
        passed=dict(collecting)
        passed.update({"exact_final_games":60,"exact_transfer_status":"PASS_FINAL_ONLY"})
        h2,a2,meta2=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",passed)
        self.assertTrue(meta2["active"]); self.assertNotEqual((h2,a2),(5.0,4.0))

    def test_final_run_mean_prior_rejects_stale_generation_even_if_marked_active(self):
        stale={
            "active":True,"historical_candidate_active":True,"phase_scope":"FINAL",
            "model_generation":"older-generation","exact_final_games":50,"exact_transfer_required_games":20,
            "exact_transfer_status":"PASS_FINAL_ONLY","model":{"home_bias":.1,"away_bias":.1,"slope_delta":0,"max_adjustment":.75},
        }
        h,a,meta=v13_run_mean_runtime.apply_pair(5.0,4.0,"FINAL",stale)
        self.assertEqual((h,a),(5.0,4.0)); self.assertFalse(meta["active"])
        self.assertEqual(meta["reason"],"FINAL_TRANSFER_MODEL_GENERATION_MISMATCH")

    def test_distribution_prior_rejects_stale_generation_and_allows_valid_current_generation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"dist.json"
            path.write_text(json.dumps(self._distribution_artifact()),encoding="utf-8")
            stale=v13_distribution_prior.load(path)
            self.assertFalse(stale["active"])
            self.assertEqual(stale["status"],"CURRENT_GENERATION_TRANSFER_REQUIRED")
            current=self._distribution_artifact(contract.MODEL_GENERATION_FINGERPRINT)
            path.write_text(json.dumps(current),encoding="utf-8")
            active=v13_distribution_prior.load(path)
            self.assertTrue(active["active"])
            self.assertEqual(active["status"],"ACTIVE_VALIDATED_CURRENT_GENERATION_FINAL_ONLY")

    def test_training_policy_accepts_exact_baseline_but_keeps_legacy_2026_research_only(self):
        text=Path("v11/v13_train.py").read_text(encoding="utf-8")
        self.assertIn('"exact_v13_replay_backfill_allowed": True',text)
        self.assertIn('"accepted_exact_replay_probability_field": "p_replay_baseline_raw"',text)
        self.assertIn('"exact_replay_layered_probability_forbidden": True',text)
        self.assertIn('"legacy_reconstructed_1801_allowed_as_native_calibration": False',text)
        self.assertIn('"research-walk-forward-only"',text)

    def test_backfill_workflow_rebuilds_calibration_and_historical_validation(self):
        text=Path(".github/workflows/v13-historical-backfill.yml").read_text(encoding="utf-8")
        self.assertIn("python -m v11.v13_run_mean_prior", text)
        self.assertIn("python -m v11.v13_distribution_prior", text)
        self.assertIn("python -m v11.v13_historical_validation", text)
        self.assertIn("python -m v11.v13_train", text)
        self.assertIn("data/v13_historical_validation.json", text)
        self.assertIn("data/v13_baseball_calibration.json", text)
        self.assertIn("PASS_FINAL_ONLY", text)
        self.assertIn("MODEL_GENERATION_FINGERPRINT", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("schedule:", text)
        self.assertIn("- cron: '20 7 * * *'", text)
        self.assertIn("group: mlb-betting-bot-state", text)
        self.assertIn("exact_transfer_bootstrap", text)
        self.assertIn("MIN_EXACT_FINAL", text)

    def test_transfer_backfill_uses_persisted_pre_candidate_baseline(self):
        runtime=Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        engine=Path("v11/v13_engine.py").read_text(encoding="utf-8")
        backfill=Path("v11/v13_historical_backfill.py").read_text(encoding="utf-8")
        run_mean=Path("v11/v13_run_mean_prior.py").read_text(encoding="utf-8")
        self.assertIn("v13_validation_baseline_home_mu", engine)
        self.assertIn('payload["v13_validation_baseline"]', runtime)
        self.assertIn("p_replay_baseline_raw", backfill)
        self.assertIn("v13-pre-candidate-score-distribution", backfill)
        self.assertIn("validation_baseline_home_runs", backfill)
        self.assertIn('row.get("validation_baseline_home_runs")', run_mean)
        self.assertIn('row.get("validation_baseline_away_runs")', run_mean)
        self.assertIn('row.get("validation_baseline_dispersion")', run_mean)
        self.assertNotIn('row.get("projected_home_runs")', run_mean)
        self.assertNotIn('row.get("projected_away_runs")', run_mean)

    def test_historical_posterior_validation_is_blocked_walk_forward(self):
        text=Path("v11/v13_historical_validation.py").read_text(encoding="utf-8")
        self.assertIn("blocked chronological by whole game",text)
        self.assertIn("strictly earlier game blocks",text)
        self.assertIn("p_replay_baseline_raw",text)
        self.assertIn("sharp_weight",text)
        self.assertIn("exact-replay-blocked-walk-forward",text)

    def test_runtime_metadata_separates_software_contract_and_generation(self):
        text=Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        self.assertIn('payload["software_version"] = VERSION', text)
        self.assertIn('payload["probability_contract_version"] = PREDICTIVE_CONTRACT_VERSION', text)
        self.assertIn('payload["model_generation"] = MODEL_GENERATION_FINGERPRINT', text)
        self.assertNotIn('payload["probability_contract_version"] = VERSION', text)

    def test_selector_labels_match_v1352_generation(self):
        text=Path("v11/selector.py").read_text(encoding="utf-8")
        self.assertIn('"selector_version": "V13.5.2-professional-portfolio-v1"', text)
        self.assertIn('"non retenu par V13.5.2"', text)
        self.assertNotIn('"non retenu par V13.5"', text)

    def test_self_test_allows_valid_future_prior_promotion(self):
        text=Path("v11/v13_entry.py").read_text(encoding="utf-8")
        self.assertNotIn('assert not mean_prior.get("active")', text)
        self.assertIn('if mean_prior.get("active"):', text)
        self.assertIn('assert observed >= required', text)
        self.assertIn('assert status == "PASS_FINAL_ONLY"', text)
        self.assertIn('if dist.get("active"):', text)
        self.assertIn('MODEL_GENERATION_FINGERPRINT', text)
        self.assertIn('exact_transfer_bootstrap', text)
        self.assertIn('walk_forward', text)

    def test_runtime_restores_both_standard_runline_pairs(self):
        engine=Path("v11/v13_engine.py").read_text(encoding="utf-8")
        runtime=Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        self.assertIn('for home_point in (-1.5, 1.5):', engine)
        self.assertIn('"v13-standard-1.5"', engine)
        self.assertIn('(away, "away", -home_point)', engine)
        self.assertNotIn('engine_v12._analysis_points = v13_analysis_points', runtime)

    def test_discord_shows_truthful_per_team_lineup_and_starter_status(self):
        text=Path("v11/discord_v13.py").read_text(encoding="utf-8")
        self.assertIn('CONFIRMÉE {min(count, 9)}/9', text)
        self.assertIn('PARTIELLE {count}/9', text)
        self.assertIn('NON PUBLIÉE', text)
        self.assertIn('PROBABLE/ANNONCÉ', text)
        self.assertIn('Lineups & starters', text)
        self.assertNotIn('PROJETÉE', text)

    def test_runtime_exposes_primary_predictive_probability_without_promoting_posterior(self):
        runtime=Path("v11/v13_runtime.py").read_text(encoding="utf-8")
        engine=Path("v11/v13_engine.py").read_text(encoding="utf-8")
        self.assertIn('option["p_predictive_final"] = round(calibrated, 6)', runtime)
        self.assertIn('option["p_predictive_final"] = round(calibrated, 6)', engine)
        self.assertIn('"BASEBALL_PRIMARY_POSTERIOR_SHADOW"', runtime)
        self.assertIn('result["primary_probability_field"] = "p_predictive_final"', engine)

    def test_discord_is_analytics_first_and_suppresses_recommendation_cards(self):
        text=Path("v11/discord_v13.py").read_text(encoding="utf-8")
        self.assertIn("Probabilité principale", text)
        self.assertIn("ensemble candidat", text)
        self.assertIn("COLLECTING", text)
        self.assertIn("def send_top(results):", text)
        self.assertIn("def send_plan(chosen, combo, portfolio, pool):", text)
        self.assertNotIn("✅ RECOMMANDÉ", text)

    def test_tracking_persists_probability_products_separately(self):
        text=Path("v11/v13_daily_tracking.py").read_text(encoding="utf-8")
        self.assertIn('"p_baseball_calibrated":calibrated', text)
        self.assertIn('"p_posterior":o.get("p_posterior")', text)
        self.assertIn('"p_predictive_final":predictive_final', text)
        self.assertIn('"calibration_source_v13":o.get("calibration_source_v13")', text)

    def test_postmortem_scores_posterior_against_baseball_on_paired_rows(self):
        rows=[
            {"settled_result":"WIN","p_model":.60,"p_baseball_calibrated":.60,"p_posterior":.70,"p_predictive_final":.60,"p_market":.65},
            {"settled_result":"LOSS","p_model":.40,"p_baseball_calibrated":.40,"p_posterior":.30,"p_predictive_final":.40,"p_market":.35},
        ]
        m=v13_daily_postmortem._metrics_from_independent(rows,rows)
        self.assertEqual(m["baseball"]["n"],2)
        self.assertEqual(m["posterior"]["n"],2)
        self.assertGreater(m["comparisons"]["posterior_vs_baseball"]["brier_improvement"],0)
        self.assertEqual(m["posterior_promotion_daily"]["status"],"COLLECTING")

    def test_posterior_promotion_combines_historical_and_live_without_double_counting(self):
        historical=[{"game_pk":1,"phase":"FINAL","market":"ML","settled_result":"WIN",
                     "p_baseball_calibrated":.60,"p_posterior":.65,"evidence_origin":"exact-replay-blocked-walk-forward"}]
        live=[{"game_pk":2,"phase":"FINAL","market":"ML","settled_result":"LOSS","canonical":True,
              "p_baseball_calibrated":.40,"p_posterior":.35,"p_predictive_final":.40,
              "predictive_final_status":"BASEBALL_PRIMARY_POSTERIOR_SHADOW","observation_at":"2026-08-18T10:00:00+00:00",
              "home":"Home","pick":"Home"}]
        evidence=v13_daily_postmortem._cumulative_promotion("ML",live,historical)
        self.assertEqual(evidence["comparison"]["n"],2)
        self.assertEqual(evidence["readiness"]["historical_exact_oos"],1)
        self.assertEqual(evidence["readiness"]["live_current_generation"],1)
        self.assertEqual(evidence["readiness"]["status"],"COLLECTING")


if __name__ == "__main__":
    unittest.main()
