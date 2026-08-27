from datetime import datetime, timezone
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification import evaluate as certify
from v14.environment_physics_challenger import evaluate as environment
from v14.execution_market import best_execution
from v14.historical_pit import reject_live_season_backfill
from v14.inning_simulator_challenger import _advance_transitions, expected_nine_inning_runs, neutral_pa_from_runs, simulate
from v14.model import RunProjection
from v14.probability_calibration import build_artifact, observations
from v14.residual_challenger import FEATURE_NAMES, offense_vs_opponent_features
from v14.statcast_shadow import build_shadow_features
from v14.total_market import total_probabilities
from v14.tracking import performance_report
from v14.true_talent_challenger import offense_component

NOW=datetime(2026,8,26,14,0,tzinfo=timezone.utc)
FRESH="2026-08-26T13:00:00+00:00"
OBSERVED="2026-08-26T12:00:00+00:00"


def settled(game_pk,game_date,analyzed_at,phase,home_score=5,away_score=3,sharp=True,total_line=8.5):
    row={"model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"game_pk":str(game_pk),"game_date":game_date,"target_date":game_date[:10],"analyzed_at":analyzed_at,"phase":phase,"settled":True,"home_score":home_score,"away_score":away_score,"home_mu":4.5,"away_mu":4.0,"total_line":total_line,"probabilities":{"home_ml":.60,"away_ml":.40,"home_minus_1_5":.42,"away_plus_1_5":.58,"away_minus_1_5":.24,"home_plus_1_5":.76,"over":.55,"under":.45},"raw_probabilities":{"home_ml":.61,"away_ml":.39,"home_minus_1_5":.43,"away_plus_1_5":.57,"away_minus_1_5":.23,"home_plus_1_5":.77,"over":.56,"under":.44}}
    if sharp: row["sharp_market"]={"selections":{"home_ml":{"fair_probability":.56},"home_minus_1_5":{"fair_probability":.38},"away_minus_1_5":{"fair_probability":.28},"over":{"fair_probability":.52}}}
    return row


class V144ProfessionalDataModelTests(unittest.TestCase):
    def test_phase_calibration_keeps_one_snapshot_per_game_phase(self):
        rows=[settled(1,"2026-08-25T23:00:00Z","2026-08-25T12:00:00Z","EARLY"),settled(1,"2026-08-25T23:00:00Z","2026-08-25T22:00:00Z","FINAL")]; artifact=build_artifact(rows); self.assertEqual(artifact["calibrators"]["MARKET:ML"]["n"],1); self.assertEqual(artifact["calibrators"]["PHASE:EARLY:ML"]["n"],1); self.assertEqual(artifact["calibrators"]["PHASE:FINAL:ML"]["n"],1)

    def test_total_push_is_excluded_from_binary_calibration(self):
        row=settled(9,"2026-08-25T23:00:00Z","2026-08-25T22:00:00Z","FINAL",home_score=5,away_score=3,total_line=8.0); obs=observations([row]); self.assertEqual(len(obs.get("ML") or []),1); self.assertEqual(len(obs.get("TOTAL_OVER") or []),0)

    def test_sharp_benchmark_is_strictly_paired(self):
        rows=[settled(1,"2026-08-25T20:00:00Z","2026-08-25T18:00:00Z","FINAL",sharp=True),settled(2,"2026-08-25T21:00:00Z","2026-08-25T18:30:00Z","FINAL",sharp=False)]; report=performance_report(rows); sharp=report["markets"]["ML"]["sharp_benchmark"]; self.assertEqual(report["markets"]["ML"]["n"],2); self.assertEqual(sharp["paired_n"],1); self.assertEqual(sharp["model_paired"]["n"],1)

    def test_certification_can_authorize_only_one_market(self):
        markets={}; calibrators={}
        for market in ("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER"):
            good=market=="ML"; markets[market]={"n":500 if good else 20,"ece":.02 if good else .20,"sharp_benchmark":{"paired_n":500 if good else 20,"brier_gain_ci95_lower":.002 if good else -.02,"logloss_gain_ci95_lower":0.0 if good else -.02,"brier_gain_vs_sharp":.01,"logloss_gain_vs_sharp":.01}}; calibrators[f"MARKET:{market}"]={"accepted":good,"active":False,"status":"VALIDATED_IDENTITY" if good else "COLLECTING"}
        perf={"schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"games_settled":700,"markets":markets,"segments":{"rolling":{"60d":{"through":OBSERVED,"markets":{}}}}}
        cal={"schema":"pulsar-v14-calibration-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"latest_observation_at":OBSERVED,"calibrators":calibrators}
        paper={"schema":"pulsar-v14-paper-bet-performance-v6","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"by_market":{"ML":{"latest_certified_close_at":FRESH,"certification_clv":{"n":120,"mean_clv":.7,"positive_rate":.56,"mean_clv_ci95_lower":.1},"execution_clv":{"n":80,"mean_clv":.3,"positive_rate":.55,"mean_clv_ci95_lower":.05}}}}
        out=certify(perf,cal,paper,now=NOW); self.assertTrue(out["certified"]); self.assertTrue(out["markets"]["ML"]["betting_certified"]); self.assertFalse(out["markets"]["TOTAL_OVER"]["betting_certified"])

    def test_residual_home_offense_uses_away_pitching(self):
        row={"training_features":{"point_in_time":True,"home_lineup":{"weighted_ops":.800,"coverage":1},"away_lineup":{"weighted_ops":.700,"coverage":1},"home_starter":{"era":1.0,"whip":1,"k9":10,"bb9":2,"hr9":.8},"away_starter":{"era":7.0,"whip":2,"k9":5,"bb9":5,"hr9":2},"bullpen":{"home":{"relievers":[]},"away":{"relievers":[]}},"operational":{"home":{},"away":{}},"environment":{},"statcast_shadow":{},"research_challengers":{}}}; x=offense_vs_opponent_features(row,"home"); self.assertAlmostEqual(x[FEATURE_NAMES.index("opp_starter_era")],7.0); self.assertAlmostEqual(x[FEATURE_NAMES.index("off_lineup_ops")],.800)

    def test_statcast_staleness_is_visible_and_not_promotion_ready(self):
        artifact={"schema":"v13-7-statcast-id-priors-v1","point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-08-01","hitters":{},"pitchers":{}}; out=build_shadow_features({"context":{},"features":{}},target_date="2026-08-25",artifact=artifact); self.assertEqual(out["freshness"],"STALE"); self.assertFalse(out["promotion_ready"])

    def test_integer_total_has_explicit_push_mass(self):
        p=RunProjection(game_pk="1",game_date="2026-08-25T20:00:00Z",analyzed_at="2026-08-25T18:00:00Z",home="H",away="A",home_mu=4.5,away_mu=4.0,total_line=8.5); out=total_probabilities(p,line=8.0); self.assertEqual(out["line_type"],"INTEGER"); self.assertGreater(out["push_probability"],0); self.assertAlmostEqual(out["complement_check"],1.0,places=10)

    def test_weather_needs_venue_baseline_for_promotion(self):
        raw={"temperature_f":80,"humidity_pct":50,"pressure_hpa":1010,"wind_mph":10,"wind_direction_deg":180,"outfield_bearing_deg":0}; diagnostic=environment(raw); self.assertFalse(diagnostic["promotion_ready"]); ready=environment({**raw,"venue_baseline_density_kg_m3":1.18,"venue_baseline_wind_out_mph":2.0}); self.assertTrue(ready["promotion_ready"])

    def test_historical_backfill_rejects_live_season_endpoint(self):
        with self.assertRaisesRegex(ValueError,"historical leakage"): reject_live_season_backfill(target_game_date="2025-05-01T20:00:00Z",retrieved_at="2026-08-25T00:00:00Z",source_type="mlb_stats_season_live")

    def test_execution_market_line_shops_verified_books(self):
        event={"home_team":"Home","away_team":"Away","bookmakers":[{"key":"winamax_fr","last_update":"2026-08-25T17:59:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.90},{"name":"Away","price":2.00}]}]},{"key":"pinnacle","last_update":"2026-08-25T17:59:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.95},{"name":"Away","price":1.95}]}]}]}; out=best_execution(event,total_line=8.5,as_of="2026-08-25T18:00:00Z"); self.assertEqual(out["selections"]["home_ml"]["price"],1.95); self.assertEqual(out["selections"]["home_ml"]["bookmaker"],"pinnacle")

    def test_hitter_k_minus_bb_has_correct_offensive_direction(self):
        matchup={"status":"READY_SHADOW","matchup_xwoba":.320}; running={"status":"READY_SHADOW","baserunning_run_adjustment":0.0}; low_k={"promotion_ready":True,"xwoba":.320,"hard_hit_rate":.38,"barrel_rate":.08,"k_minus_bb_rate":.06}; high_k={"promotion_ready":True,"xwoba":.320,"hard_hit_rate":.38,"barrel_rate":.08,"k_minus_bb_rate":.20}; good=offense_component(low_k,matchup,running); bad=offense_component(high_k,matchup,running); self.assertGreater(good["score"],bad["score"]); self.assertGreater(good["run_adjustment"],bad["run_adjustment"])

    def test_pa_simulator_is_calibrated_to_structural_full_nine_mean(self):
        pa=neutral_pa_from_runs(4.45); self.assertAlmostEqual(expected_nine_inning_runs(pa),4.45,places=7)
        for probability,bases,runs in _advance_transitions("1B",(True,False,False)): self.assertGreater(probability,0); self.assertEqual(sum(bool(v) for v in bases)+runs,2)
        out=simulate(home_mu=4.5,away_mu=4.0,n=1000,seed=7,total_line=8.0); self.assertAlmostEqual(out["total"]["complement_check"],1.0,places=12); self.assertAlmostEqual(out["pa_calibration"]["calibrated_home_full_nine_runs"],4.5,places=7); self.assertTrue(out["rules"]["walkoff_resolution"])

if __name__=="__main__": unittest.main()
