import unittest

from v14 import MODEL_GENERATION
from v14.pipeline import predict_from_result, predict_from_structural
from v14.run_stack import StructuralRunInput


def _starter(name, era, whip, k9=8.5, bb9=3.0, hr9=1.1, ip=100):
    return {
        "name": name,
        "stats": {
            "era": era,
            "whip": whip,
            "strikeoutsPer9Inn": k9,
            "walksPer9Inn": bb9,
            "homeRunsPer9": hr9,
            "inningsPitched": ip,
        },
    }


def _lineup(ops):
    return {"confirmed": True, "players": [{"name": f"H{i}", "ops": ops} for i in range(9)]}


def _result():
    return {
        "game_pk": "123",
        "game_date": "2026-08-25T23:00:00+00:00",
        "analyzed_at": "2026-08-25T18:00:00+00:00",
        "phase": "FINAL",
        "home": "Home",
        "away": "Away",
        "model_generation": "legacy-input",
        "game": {"venue": {"name": "Unknown Test Park"}},
        "features": {
            "structural_home_mu": 4.5,
            "structural_away_mu": 4.2,
            "park_factor_runtime": {
                "static_factor": 1.0,
                "venue": "Unknown Test Park",
                "active": False,
            },
            "historical_bootstrap": {
                "run_prior": {"active": False},
                "v13_run_mean_prior": {"active": False},
            },
            "learned_run_adjustment": {"active": False},
            "run_dispersion": 7.5,
            "run_environment_sigma": 0.08,
            "extra_innings_home_probability": 0.5,
        },
    }


def _feature(as_of="2026-08-25T17:30:00+00:00"):
    return {
        "game_pk": "123",
        "as_of": as_of,
        "point_in_time": True,
        "point_in_time_validation_reasons": [],
        "data_quality": {"eligible": True},
        "context": {
            "home_starter": _starter("Home SP", 3.1, 1.12, k9=9.8, bb9=2.2, hr9=.8, ip=140),
            "away_starter": _starter("Away SP", 5.6, 1.52, k9=6.4, bb9=3.9, hr9=1.7, ip=105),
            "home_lineup": _lineup(.820),
            "away_lineup": _lineup(.670),
        },
        "features": {},
        "rich_modules": {},
    }


class V14PipelineTests(unittest.TestCase):
    def test_pipeline_returns_production_v14_surface(self):
        out = predict_from_result(_result(), total_line=8.5, feature_row=_feature())
        self.assertEqual(out["role"], "PRODUCTION")
        self.assertEqual(out["model_generation"], MODEL_GENERATION)
        self.assertFalse(out["market_probability_used_as_feature"])
        self.assertTrue(out["context_adjustment"]["eligible"])
        self.assertNotEqual(out["run_projection"]["home_mu"], out["base_run_projection"]["home_mu"])
        p = out["probabilities"]
        self.assertAlmostEqual(p["home_ml"] + p["away_ml"], 1.0, places=12)
        self.assertAlmostEqual(p["home_minus_1_5"] + p["away_plus_1_5"], 1.0, places=12)
        self.assertAlmostEqual(p["home_plus_1_5"] + p["away_minus_1_5"], 1.0, places=12)
        self.assertAlmostEqual(p["over"] + p["under"], 1.0, places=12)

    def test_native_structural_boundary_needs_no_legacy_result(self):
        structural = StructuralRunInput(
            game_pk="123",
            game_date="2026-08-25T23:00:00+00:00",
            venue="Unknown Test Park",
            structural_home_mu=4.5,
            structural_away_mu=4.2,
            static_park_factor=1.0,
        )
        out = predict_from_structural(
            structural,
            analyzed_at="2026-08-25T18:00:00+00:00",
            home="Home",
            away="Away",
            total_line=8.5,
            feature_row=_feature(),
            extra_innings_home_probability=.5,
        )
        self.assertEqual(out["role"], "PRODUCTION")
        self.assertEqual(out["model_generation"], MODEL_GENERATION)
        self.assertEqual(out["source_generation"], "pulsar-v14-native-structural")
        self.assertTrue(out["context_adjustment"]["eligible"])
        self.assertFalse(out["market_probability_used_as_feature"])

    def test_future_feature_is_rejected(self):
        out = predict_from_result(
            _result(),
            total_line=8.5,
            feature_row=_feature("2026-08-25T19:00:00+00:00"),
        )
        self.assertFalse(out["context_adjustment"]["eligible"])
        self.assertEqual(out["context_adjustment"]["home_delta"], 0.0)
        self.assertEqual(out["context_adjustment"]["away_delta"], 0.0)
        self.assertEqual(out["run_projection"]["home_mu"], out["base_run_projection"]["home_mu"])
        self.assertEqual(out["run_projection"]["away_mu"], out["base_run_projection"]["away_mu"])

    def test_whole_run_total_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "half-run"):
            predict_from_result(_result(), total_line=8.0, feature_row=_feature())


if __name__ == "__main__":
    unittest.main()
