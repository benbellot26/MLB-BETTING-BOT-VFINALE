import unittest

from v14.context_shadow import build_context_shadow


def starter(name, era, whip, bb9, hr9, k9, ip=100):
    return {"name": name, "stats": {"era": era, "whip": whip, "walksPer9Inn": bb9, "homeRunsPer9": hr9, "strikeoutsPer9Inn": k9, "inningsPitched": ip}}


def lineup(ops):
    return {"confirmed": True, "players": [{"name": f"H{i}", "ops": ops} for i in range(9)]}


def result():
    return {"game_pk": "123", "game_date": "2026-08-25T00:00:00+00:00", "analyzed_at": "2026-08-24T12:00:00+00:00", "phase": "FINAL", "home": "Home", "away": "Away", "features": {"home_mu": 4.5, "away_mu": 4.2, "run_dispersion": 7.5, "run_environment_sigma": 0.08, "extra_innings_home_probability": 0.5}, "options": [{"market": "TOTAL", "name": "Over", "point": 8.5, "is_canonical_line": True}], "ctx": {"home": "Home", "away": "Away"}, "model_generation": "V13.10"}


class ContextShadowTests(unittest.TestCase):
    def test_safe_context_modifies_only_shadow_run_means(self):
        feature = {"schema": "v13-pit-feature-store-v1", "game_pk": "123", "as_of": "2026-08-24T11:30:00+00:00", "point_in_time": True, "point_in_time_validation_reasons": [], "data_quality": {"eligible": True}, "context": {"home_starter": starter("Home SP", 3.0, 1.1, 2.0, .8, 10.0, 150), "away_starter": starter("Away SP", 5.7, 1.52, 3.8, 1.7, 6.4, 100), "home_lineup": lineup(.810), "away_lineup": lineup(.660)}, "features": {}, "rich_modules": {}}
        out = build_context_shadow(result(), feature_row=feature)
        self.assertEqual(out["role"], "SHADOW_ONLY")
        self.assertFalse(out["affects_production"])
        self.assertFalse(out["market_probability_used_as_feature"])
        self.assertGreater(out["run_projection"]["home_mu"], 4.5)
        self.assertLess(out["run_projection"]["away_mu"], 4.2)
        self.assertEqual(out["champion_reference"]["home_mu"], 4.5)
        self.assertEqual(out["champion_reference"]["away_mu"], 4.2)

    def test_future_explicit_feature_row_fails_closed(self):
        feature = {"schema": "v13-pit-feature-store-v1", "game_pk": "123", "as_of": "2026-08-24T13:00:00+00:00", "point_in_time": True, "point_in_time_validation_reasons": [], "data_quality": {"eligible": True}, "context": {"away_starter": starter("Away SP", 9.0, 2.0, 6.0, 3.0, 3.0, 150)}}
        out = build_context_shadow(result(), feature_row=feature)
        self.assertEqual(out["run_projection"]["home_mu"], 4.5)
        self.assertEqual(out["run_projection"]["away_mu"], 4.2)
        self.assertFalse(out["feature_row"]["available"])
        self.assertFalse(out["context_overlay"]["eligible"])


if __name__ == "__main__":
    unittest.main()
