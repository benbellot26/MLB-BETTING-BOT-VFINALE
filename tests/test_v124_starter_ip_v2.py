import unittest
from unittest.mock import patch

from v11 import v124_starter_ip_v2 as v2


class StarterIPV2Tests(unittest.TestCase):
    def test_expected_ip_does_not_use_era_or_whip(self):
        stats = {"inningsPitched": 66.0, "gamesStarted": 12, "gamesPitched": 12}
        with patch("v11.v124_starter_ip_v2.core.player_stats", return_value=stats):
            a, meta_a = v2.expected_starter_ip_v2({"id": 1, "era": 1.80, "whip": .90})
            b, meta_b = v2.expected_starter_ip_v2({"id": 1, "era": 6.20, "whip": 1.70})
        self.assertAlmostEqual(a, b, places=12)
        self.assertFalse(meta_a["quality_used_for_duration"])
        self.assertFalse(meta_b["quality_used_for_duration"])

    def test_bullpen_uses_only_listed_relievers(self):
        result = {"features": {"bullpen": {"away": {"relievers": [
            {"id": 11, "pitches_3d": 0, "days_used": 0},
            {"id": 12, "pitches_3d": 80, "days_used": 2},
        ]}}}}
        rows = {
            11: {"inningsPitched": 40, "era": 3.0, "whip": 1.1, "strikeoutsPer9Inn": 10, "walksPer9Inn": 2.5, "homeRunsPer9": .8},
            12: {"inningsPitched": 40, "era": 4.5, "whip": 1.4, "strikeoutsPer9Inn": 8, "walksPer9Inn": 3.5, "homeRunsPer9": 1.3},
        }
        with patch("v11.v124_starter_ip_v2.core.player_stats", side_effect=lambda pid, group: rows.get(pid, {})), \
             patch("v11.v124_starter_ip_v2.core.league_baselines", return_value={"era": 4.35, "whip": 1.32}):
            q, cov, meta = v2._bullpen_quality(result, "away")
        self.assertGreater(cov, 0)
        self.assertEqual(meta["usable_relievers"], 2)
        self.assertTrue(.7 < q < 1.3)

    def test_reference_ip_produces_neutral_factor(self):
        result = {
            "ctx": {"away_starter": {"id": 7}, "home_starter": {"id": 8}},
            "features": {"bullpen": {"away": {"relievers": []}, "home": {"relievers": []}}},
        }
        with patch("v11.predictive_v124._starter", side_effect=lambda r, side: r["ctx"][f"{side}_starter"]), \
             patch("v11.predictive_v124._starter_quality", return_value=.8), \
             patch("v11.v124_starter_ip_v2.expected_starter_ip_v2", return_value=(v2.REFERENCE_STARTER_IP, {"sample": 1.0})), \
             patch("v11.v124_starter_ip_v2._bullpen_quality", return_value=(1.2, 1.0, {"usable_relievers": 7, "listed_relievers": 7})):
            out = v2.starter_ip_module_v2(result, True)
        self.assertAlmostEqual(out["home_factor"], 1.0, places=12)
        self.assertAlmostEqual(out["away_factor"], 1.0, places=12)

    def test_effect_is_marginal_and_bounded(self):
        result = {
            "ctx": {"away_starter": {"id": 7}, "home_starter": {"id": 8}},
            "features": {"bullpen": {"away": {"relievers": []}, "home": {"relievers": []}}},
        }
        with patch("v11.predictive_v124._starter", side_effect=lambda r, side: r["ctx"][f"{side}_starter"]), \
             patch("v11.predictive_v124._starter_quality", return_value=.60), \
             patch("v11.v124_starter_ip_v2.expected_starter_ip_v2", return_value=(6.7, {"sample": 1.0})), \
             patch("v11.v124_starter_ip_v2._bullpen_quality", return_value=(1.40, 1.0, {"usable_relievers": 7, "listed_relievers": 7})):
            out = v2.starter_ip_module_v2(result, True, shrink=1.0)
        self.assertGreaterEqual(out["home_factor"], .975)
        self.assertLessEqual(out["home_factor"], 1.025)
        self.assertTrue(out["details"]["home"]["duration_quality_decoupled"])
        self.assertFalse(out["details"]["home"]["absolute_pitching_quality_reapplied"])


if __name__ == "__main__":
    unittest.main()
