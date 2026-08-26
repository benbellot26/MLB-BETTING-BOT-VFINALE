import unittest

from v14.certification import evaluate as certification_status
from v14.decision import evaluate as decision_status
from v14.distribution_tuning import build as build_distribution_challenger
from v14.probability_calibration import build_artifact, calibrate_surface
from v14.residual_challenger import build as build_residual_challenger
from v14.sharp_market import power_devig, sharp_consensus
from v14.uncertainty import intervals


class V14ProfessionalHardeningTests(unittest.TestCase):
    def test_calibration_is_identity_until_strict_evidence(self):
        artifact = build_artifact([])
        self.assertTrue(all(not row.get("active") for row in artifact["calibrators"].values()))
        raw = {
            "home_ml": 0.63,
            "away_ml": 0.37,
            "home_minus_1_5": 0.41,
            "away_plus_1_5": 0.59,
            "away_minus_1_5": 0.22,
            "home_plus_1_5": 0.78,
            "over": 0.57,
            "under": 0.43,
        }
        out, meta = calibrate_surface(raw, phase="FINAL", artifact=artifact)
        for key, value in raw.items():
            self.assertAlmostEqual(out[key], value, places=12)
        self.assertFalse(meta["any_active"])
        self.assertAlmostEqual(out["home_ml"] + out["away_ml"], 1.0, places=12)
        self.assertAlmostEqual(out["over"] + out["under"], 1.0, places=12)

    def test_power_devig_is_complementary(self):
        a, b = power_devig(1.80, 2.10)
        self.assertGreater(a, 0)
        self.assertGreater(b, 0)
        self.assertAlmostEqual(a + b, 1.0, places=12)

    def test_sharp_consensus_uses_verified_sharp_books_not_display_book(self):
        analyzed_at = "2026-08-25T18:00:00Z"

        def book(key, home_price, away_price):
            return {
                "key": key,
                "last_update": "2026-08-25T17:55:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home", "price": home_price},
                            {"name": "Away", "price": away_price},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 8.5, "price": 1.91},
                            {"name": "Under", "point": 8.5, "price": 1.91},
                        ],
                    },
                ],
            }

        event = {
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [book("winamax_fr", 1.40, 3.20), book("pinnacle", 1.90, 2.00)],
        }
        sharp = sharp_consensus(event, total_line=8.5, as_of=analyzed_at)
        self.assertTrue(sharp["freshness_verified"])
        self.assertEqual(sharp["selections"]["home_ml"]["books"], ["pinnacle"])
        self.assertNotIn("winamax_fr", sharp["selections"]["home_ml"]["books"])

    def test_unverified_sharp_market_is_not_actionable(self):
        event = {
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Home", "price": 1.9},
                                {"name": "Away", "price": 2.0},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "point": 8.5, "price": 1.91},
                                {"name": "Under", "point": 8.5, "price": 1.91},
                            ],
                        },
                    ],
                }
            ],
        }
        sharp = sharp_consensus(event, total_line=8.5, as_of="2026-08-25T18:00:00Z")
        self.assertFalse(sharp["actionable"])
        self.assertFalse(sharp["freshness_verified"])

    def test_uncertainty_widens_when_starter_is_degraded(self):
        probabilities = {
            "home_ml": 0.60,
            "away_ml": 0.40,
            "home_minus_1_5": 0.40,
            "away_plus_1_5": 0.60,
            "away_minus_1_5": 0.25,
            "home_plus_1_5": 0.75,
            "over": 0.55,
            "under": 0.45,
        }
        quality = {"eligible": True, "home_lineup_count": 9, "away_lineup_count": 9}
        base = intervals(
            probabilities,
            {"markets": {}},
            data_quality=quality,
            starter_degraded=False,
            market_fresh=True,
        )
        degraded = intervals(
            probabilities,
            {"markets": {}},
            data_quality=quality,
            starter_degraded=True,
            market_fresh=True,
        )
        self.assertGreater(
            degraded["selections"]["home_ml"]["half_width_pp"],
            base["selections"]["home_ml"]["half_width_pp"],
        )

    def test_decision_can_never_bet_when_not_certified(self):
        prediction = {
            "probabilities": {"home_ml": 0.80, "away_ml": 0.20},
            "probability_intervals": {"selections": {"home_ml": {"lower": 0.75}}},
            "calibration": {"markets": {"ML": {"active": True}}},
        }
        market = {
            "freshness_verified": True,
            "markets": {"ML": {"selections": {"home": {"price": 2.00}}}},
        }
        sharp = {
            "freshness_verified": True,
            "selections": {"home_ml": {"fair_probability": 0.60}},
        }
        out = decision_status(
            prediction=prediction,
            market_snapshot=market,
            sharp_market=sharp,
            certification={"certified": False},
            starter_degraded=False,
        )
        self.assertEqual(out["best"]["status"], "RESEARCH_ONLY")
        self.assertIn("betting_not_certified", out["best"]["blockers"])

    def test_certification_is_separate_from_software_production(self):
        status = certification_status({}, {})
        self.assertFalse(status["certified"])
        self.assertFalse(status["probability_certified"])
        self.assertEqual(status["software_role"], "PRODUCTION")
        self.assertEqual(status["betting_status"], "RESEARCH_ONLY")

    def test_probability_certification_does_not_skip_paper_clv_gate(self):
        markets = {}
        calibrators = {}
        for market in ("ML", "RL_HOME_-1.5", "RL_AWAY_-1.5", "TOTAL_OVER"):
            markets[market] = {
                "n": 500,
                "ece": 0.02,
                "sharp_benchmark": {
                    "n": 500,
                    "brier_gain_vs_sharp": 0.01,
                    "logloss_gain_vs_sharp": 0.01,
                },
            }
            calibrators[f"MARKET:{market}"] = {"active": True}
        performance = {"games_settled": 700, "markets": markets}
        calibration = {"calibrators": calibrators}

        probability_only = certification_status(performance, calibration, {})
        self.assertTrue(probability_only["probability_certified"])
        self.assertFalse(probability_only["certified"])
        self.assertIn("paper_clv_n<100", probability_only["reasons"])

        betting = certification_status(
            performance,
            calibration,
            {"clv": {"n": 120, "mean_clv": 0.35, "positive_rate": 0.56}},
        )
        self.assertTrue(betting["probability_certified"])
        self.assertTrue(betting["certified"])
        self.assertEqual(betting["betting_status"], "BETTING_CERTIFIED")

    def test_challengers_never_auto_activate_with_small_samples(self):
        distribution = build_distribution_challenger([])
        residual = build_residual_challenger([])
        self.assertEqual(distribution["role"], "CHALLENGER_ONLY")
        self.assertEqual(residual["role"], "CHALLENGER_ONLY")
        self.assertFalse(distribution["auto_activation"])
        self.assertFalse(residual["auto_activation"])
        self.assertEqual(distribution["status"], "COLLECTING")
        self.assertEqual(residual["status"], "COLLECTING")


if __name__ == "__main__":
    unittest.main()
