from datetime import datetime, timezone
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification import evaluate as certification_status
from v14.decision import evaluate as decision_status
from v14.distribution_tuning import build as build_distribution_challenger
from v14.probability_calibration import build_artifact, calibrate_surface
from v14.residual_challenger import build as build_residual_challenger
from v14.sharp_market import DEFAULT_SHARP_BOOK_WEIGHTS, power_devig, sharp_consensus
from v14.uncertainty import intervals

NOW=datetime(2026,8,26,14,0,tzinfo=timezone.utc)
FRESH="2026-08-26T13:00:00+00:00"
OBSERVED="2026-08-26T12:00:00+00:00"


class V14ProfessionalHardeningTests(unittest.TestCase):
    def test_calibration_is_identity_until_strict_evidence(self):
        artifact=build_artifact([]); self.assertTrue(all(not row.get("active") for row in artifact["calibrators"].values()))
        raw={"home_ml":.63,"away_ml":.37,"home_minus_1_5":.41,"away_plus_1_5":.59,"away_minus_1_5":.22,"home_plus_1_5":.78,"over":.57,"under":.43}
        out,meta=calibrate_surface(raw,phase="FINAL",artifact=artifact)
        for key,value in raw.items(): self.assertAlmostEqual(out[key],value,places=12)
        self.assertFalse(meta["any_active"]); self.assertEqual(meta["probability_policy_id"],PROBABILITY_POLICY_ID); self.assertAlmostEqual(out["home_ml"]+out["away_ml"],1.0,places=12); self.assertAlmostEqual(out["over"]+out["under"],1.0,places=12)

    def test_power_devig_is_complementary(self):
        a,b=power_devig(1.80,2.10); self.assertGreater(a,0); self.assertGreater(b,0); self.assertAlmostEqual(a+b,1.0,places=12)

    def test_unadjusted_exchange_proxies_are_discounted_below_pinnacle(self):
        self.assertLess(DEFAULT_SHARP_BOOK_WEIGHTS["betfair_ex_eu"],DEFAULT_SHARP_BOOK_WEIGHTS["pinnacle"]); self.assertLess(DEFAULT_SHARP_BOOK_WEIGHTS["matchbook"],DEFAULT_SHARP_BOOK_WEIGHTS["pinnacle"])

    def test_sharp_consensus_uses_verified_sharp_books_not_display_book(self):
        analyzed_at="2026-08-25T18:00:00Z"
        def book(key,home_price,away_price): return {"key":key,"last_update":"2026-08-25T17:55:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":home_price},{"name":"Away","price":away_price}]},{"key":"totals","outcomes":[{"name":"Over","point":8.5,"price":1.91},{"name":"Under","point":8.5,"price":1.91}]}]}
        event={"home_team":"Home","away_team":"Away","bookmakers":[book("winamax_fr",1.40,3.20),book("pinnacle",1.90,2.00)]}; sharp=sharp_consensus(event,total_line=8.5,as_of=analyzed_at)
        self.assertTrue(sharp["freshness_verified"]); self.assertEqual(sharp["selections"]["home_ml"]["books"],["pinnacle"]); self.assertNotIn("winamax_fr",sharp["selections"]["home_ml"]["books"])

    def test_unverified_sharp_market_is_not_actionable(self):
        event={"home_team":"Home","away_team":"Away","bookmakers":[{"key":"pinnacle","markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.9},{"name":"Away","price":2.0}]},{"key":"totals","outcomes":[{"name":"Over","point":8.5,"price":1.91},{"name":"Under","point":8.5,"price":1.91}]}]}]}; sharp=sharp_consensus(event,total_line=8.5,as_of="2026-08-25T18:00:00Z"); self.assertFalse(sharp["actionable"]); self.assertFalse(sharp["freshness_verified"])

    def test_uncertainty_widens_when_starter_is_degraded(self):
        probabilities={"home_ml":.60,"away_ml":.40,"home_minus_1_5":.40,"away_plus_1_5":.60,"away_minus_1_5":.25,"home_plus_1_5":.75,"over":.55,"under":.45}; quality={"eligible":True,"home_lineup_count":9,"away_lineup_count":9}; base=intervals(probabilities,{"markets":{}},data_quality=quality,starter_degraded=False,market_fresh=True); degraded=intervals(probabilities,{"markets":{}},data_quality=quality,starter_degraded=True,market_fresh=True); self.assertGreater(degraded["selections"]["home_ml"]["half_width_pp"],base["selections"]["home_ml"]["half_width_pp"])

    def test_decision_can_never_bet_when_not_certified(self):
        prediction={"probabilities":{"home_ml":.70,"away_ml":.30},"probability_intervals":{"selections":{"home_ml":{"lower":.64}}},"calibration":{"markets":{"ML":{"active":True}}}}; market={"freshness_verified":True,"markets":{"ML":{"selections":{"home":{"price":1.80}}}}}; sharp={"freshness_verified":True,"selections":{"home_ml":{"fair_probability":.60,"source_count":2}}}; out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification={"certified":False},starter_degraded=False); self.assertEqual(out["best"]["status"],"RESEARCH_ONLY"); self.assertIn("betting_not_certified",out["best"]["blockers"])

    def test_decision_requires_lower_bound_to_beat_sharp(self):
        prediction={"probabilities":{"home_ml":.64,"away_ml":.36},"probability_intervals":{"selections":{"home_ml":{"lower":.54}}},"calibration":{"markets":{"ML":{"accepted":True}}}}; market={"freshness_verified":True,"markets":{"ML":{"selections":{"home":{"price":2.05}}}}}; sharp={"freshness_verified":True,"selections":{"home_ml":{"fair_probability":.56,"source_count":2,"sportsbook_source_count":2}}}; cert={"markets":{"ML":{"betting_certified":True}},"certified":True}; out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=cert,starter_degraded=False); self.assertEqual(out["best"]["status"],"NO_BET"); self.assertLess(out["best"]["robust_sharp_edge_pp"],0)

    def test_exchange_only_sharp_can_be_research_ready_but_never_bet(self):
        prediction={"probabilities":{"home_ml":.70,"away_ml":.30},"probability_intervals":{"selections":{"home_ml":{"lower":.66}}},"calibration":{"markets":{"ML":{"accepted":True}}}}; market={"freshness_verified":True,"markets":{"ML":{"selections":{"home":{"price":1.80}}}}}; sharp={"freshness_verified":True,"selections":{"home_ml":{"fair_probability":.60,"source_count":2,"sportsbook_source_count":0,"exchange_proxy_source_count":2}}}; cert={"markets":{"ML":{"betting_certified":True}},"certified":True}; out=decision_status(prediction=prediction,market_snapshot=market,sharp_market=sharp,certification=cert,starter_degraded=False); self.assertEqual(out["best"]["status"],"RESEARCH_ONLY"); self.assertTrue(out["best"]["research_ready"]); self.assertIn("sharp_sportsbook_source_missing_for_bet",out["best"]["blockers"])

    def test_certification_is_separate_from_software_production(self):
        status=certification_status({},{}); self.assertFalse(status["certified"]); self.assertFalse(status["probability_certified"]); self.assertEqual(status["software_role"],"PRODUCTION"); self.assertEqual(status["betting_status"],"RESEARCH_ONLY")

    def test_probability_certification_does_not_skip_executable_clv_gates(self):
        markets={}; calibrators={}
        for market in ("ML","RL_HOME_-1.5","RL_AWAY_-1.5","TOTAL_OVER"):
            markets[market]={"n":500,"ece":.02,"sharp_benchmark":{"paired_n":500,"brier_gain_ci95_lower":.002,"logloss_gain_ci95_lower":0.0,"brier_gain_vs_sharp":.01,"logloss_gain_vs_sharp":.01}}; calibrators[f"MARKET:{market}"]={"accepted":True,"active":False,"status":"VALIDATED_IDENTITY"}
        performance={"schema":"pulsar-v14-performance-v5","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"games_settled":700,"markets":markets,"segments":{"rolling":{"60d":{"through":OBSERVED,"markets":{}}}}}; calibration={"schema":"pulsar-v14-calibration-v3","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"latest_observation_at":OBSERVED,"calibrators":calibrators}
        probability_only=certification_status(performance,calibration,{},now=NOW); self.assertTrue(probability_only["probability_certified"]); self.assertFalse(probability_only["certified"]); self.assertIn("paper_certification_clv_n<100",probability_only["reasons"])
        evidence={"n":120,"mean_clv":.35,"positive_rate":.56,"mean_clv_ci95_lower":.05}; execution={"n":80,"mean_clv":.20,"positive_rate":.55,"mean_clv_ci95_lower":.02}; paper={"schema":"pulsar-v14-paper-bet-performance-v7","model_generation":MODEL_GENERATION,"probability_policy_id":PROBABILITY_POLICY_ID,"generated_at":FRESH,"by_market":{m:{"latest_certified_close_at":FRESH,"certification_clv":evidence,"execution_clv":execution} for m in markets}}
        betting=certification_status(performance,calibration,paper,now=NOW); self.assertTrue(betting["probability_certified"]); self.assertTrue(betting["certified"]); self.assertEqual(betting["betting_status"],"BETTING_CERTIFIED")

    def test_challengers_never_auto_activate_with_small_samples(self):
        distribution=build_distribution_challenger([]); residual=build_residual_challenger([]); self.assertEqual(distribution["role"],"CHALLENGER_ONLY"); self.assertEqual(residual["role"],"CHALLENGER_ONLY"); self.assertFalse(distribution["auto_activation"]); self.assertFalse(residual["auto_activation"]); self.assertEqual(distribution["status"],"COLLECTING"); self.assertEqual(residual["status"],"COLLECTING")

if __name__=="__main__": unittest.main()
