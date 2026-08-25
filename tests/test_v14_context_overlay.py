import unittest

from v14.context_overlay import (
    MAX_TEAM_DELTA,
    bullpen_stress,
    context_overlay_from_feature_row,
    environment_signal,
    h2h_micro_signal,
    lineup_strength,
    starter_vulnerability,
)


def starter(name, era, whip, bb9, hr9, k9, ip=100):
    return {"name": name, "stats": {"era": era, "whip": whip, "walksPer9Inn": bb9, "homeRunsPer9": hr9, "strikeoutsPer9Inn": k9, "inningsPitched": ip}}


def lineup(ops):
    return {"confirmed": True, "status": "CONFIRMED", "players": [{"name": f"H{i}", "ops": ops} for i in range(9)]}


def bullpen(stressed):
    relievers = []
    for i in range(7):
        relievers.append({"name": f"R{i}", "taxed": stressed and i < 4, "likely_unavailable": stressed and i < 2, "available": not (stressed and i < 2), "uses_last_3d": 3 if stressed else 0, "pitches_last_3d": 55 if stressed else 8})
    return {"coverage": 1.0, "relievers": relievers}


class ContextOverlayTests(unittest.TestCase):
    def test_weak_starter_residual_scores_more_vulnerable(self):
        weak = starter_vulnerability(starter("Weak", 5.42, 1.47, 3.55, 1.58, 6.78, 92))
        good = starter_vulnerability(starter("Good", 3.10, 1.12, 2.1, 0.8, 9.8, 140))
        self.assertTrue(weak.available)
        self.assertTrue(good.available)
        self.assertGreater(weak.score, good.score)
        self.assertGreater(weak.delta, good.delta)

    def test_missing_starter_fails_closed(self):
        signal = starter_vulnerability({})
        self.assertFalse(signal.available)
        self.assertEqual(signal.delta, 0.0)

    def test_lineup_ops_is_not_double_counted(self):
        base = lineup_strength(lineup(.800))
        self.assertFalse(base.available)
        self.assertEqual(base.delta, 0.0)
        rich = {"home": {"statcast_lineup": {"status": "ACTIVE", "xwoba": .350, "platoon_factor": 1.05}}}
        residual = lineup_strength(lineup(.800), rich, "home")
        self.assertTrue(residual.available)
        self.assertGreater(residual.delta, 0.0)

    def test_lineup_requires_nine_confirmed_hitters(self):
        short = {"confirmed": True, "players": [{"ops": .800} for _ in range(8)]}
        self.assertFalse(lineup_strength(short).available)

    def test_stressed_bullpen_scores_higher(self):
        stressed = bullpen_stress(bullpen(True))
        rested = bullpen_stress(bullpen(False))
        self.assertTrue(stressed.available)
        self.assertTrue(rested.available)
        self.assertGreater(stressed.score, rested.score)
        self.assertGreater(stressed.delta, rested.delta)

    def test_h2h_is_explicitly_disabled(self):
        signal = h2h_micro_signal({"hits": 15, "at_bats": 30})
        self.assertFalse(signal.available)
        self.assertEqual(signal.delta, 0.0)
        self.assertIn("disabled", signal.reason.lower())

    def test_environment_is_bounded(self):
        hot_out = environment_signal({"available": True, "temperature_f": 92, "wind": "14 mph, Out To CF", "wind_mph": 14, "roof": "Open"})
        closed = environment_signal({"available": True, "temperature_f": 92, "wind": "14 mph, Out To CF", "wind_mph": 14, "roof": "Closed"})
        self.assertGreater(hot_out.delta, 0.0)
        self.assertEqual(closed.delta, 0.0)

    def test_ineligible_row_is_exact_noop(self):
        out = context_overlay_from_feature_row({"point_in_time": True, "data_quality": {"eligible": False}}, 4.5, 4.2)
        self.assertFalse(out["eligible"])
        self.assertEqual(out["home_mu"], 4.5)
        self.assertEqual(out["away_mu"], 4.2)

    def test_overlay_is_capped_and_market_free(self):
        row = {
            "point_in_time": True,
            "point_in_time_validation_reasons": [],
            "data_quality": {"eligible": True},
            "context": {
                "home_starter": starter("Home", 3.0, 1.1, 2.0, 0.7, 10.0, 150),
                "away_starter": starter("Away", 6.2, 1.65, 4.5, 2.0, 5.5, 120),
                "home_lineup": lineup(.850),
                "away_lineup": lineup(.630),
            },
            "features": {
                "bullpen": {"home": bullpen(False), "away": bullpen(True)},
                "environment": {"available": False},
            },
            "rich_modules": {},
        }
        out = context_overlay_from_feature_row(row, 4.5, 4.2)
        self.assertTrue(out["eligible"])
        self.assertLessEqual(abs(out["home_delta"]), MAX_TEAM_DELTA)
        self.assertLessEqual(abs(out["away_delta"]), MAX_TEAM_DELTA)
        self.assertFalse(out["market_probability_used_as_feature"])
        self.assertGreater(out["home_mu"], 4.5)
        self.assertLess(out["away_mu"], 4.2)


if __name__ == "__main__":
    unittest.main()
