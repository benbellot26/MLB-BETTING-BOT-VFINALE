from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import v124_weight_optimizer as opt


class V124WeightOptimizerTests(unittest.TestCase):
    def row(self, i, starter_signal=True):
        y = 1 if i % 3 != 0 else 0
        home, away = "Home", "Away"
        hs, aws = (6, 3) if y else (3, 6)
        base_home = .56
        starter_home = (.76 if y else .24) if starter_signal else base_home

        def pair(ph):
            return [
                {"market": "ML", "name": home, "point": None, "p_effective": ph},
                {"market": "ML", "name": away, "point": None, "p_effective": 1-ph},
            ]

        official = [
            {"market": "ML", "name": home, "point": None, "result": "WIN" if y else "LOSS"},
            {"market": "ML", "name": away, "point": None, "result": "LOSS" if y else "WIN"},
        ]
        variants = {
            "baseline_v1232": {"home_mu": 4.5, "away_mu": 4.3, "options": pair(base_home)},
        }
        modules = {}
        for name in opt.MODULES:
            ph = starter_home if name == "starter_ip" else base_home
            if name == "starter_ip":
                hf, af = ((1.06, .94) if y else (.94, 1.06))
            else:
                hf = af = 1.0
            variants[f"only_{name}"] = {
                "home_mu": 4.5*hf, "away_mu": 4.3*af,
                "home_factor": hf, "away_factor": af, "options": pair(ph),
            }
            modules[name] = {"status": "ACTIVE", "coverage": 1.0, "home_factor": hf, "away_factor": af}
        return {
            "game_pk": 1000+i, "game_date": f"2026-07-{1+(i//4):02d}T{(i%4)*3:02d}:00:00Z",
            "home_score": hs, "away_score": aws, "options": official,
            "shadow_v124": {
                "enabled": True, "base_home_mu": 4.5, "base_away_mu": 4.3,
                "modules": modules, "variants": variants,
            },
        }

    def rows(self, n):
        return [self.row(i) for i in range(n)]

    def test_collects_below_75_without_activation(self):
        with patch.object(opt, "_BOOTSTRAPS", 20):
            model = opt.build_model(self.rows(40))
        self.assertEqual(model["status"], "COLLECTING")
        self.assertFalse(model["active_for_v124_shadow"])
        self.assertFalse(model["affects_v12_selection"])
        self.assertTrue(all(v == 0 for v in model["weights"].values()))

    def test_optimizer_learns_useful_module_and_bounds_weights(self):
        with patch.object(opt, "_BOOTSTRAPS", 40):
            model = opt.build_model(self.rows(90))
        self.assertEqual(model["status"], "EXPERIMENTAL_SHADOW")
        self.assertTrue(model["active_for_v124_shadow"])
        self.assertGreater(model["weights"]["starter_ip"], .5)
        for value in model["weights"].values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, opt.MAX_WEIGHT)
        self.assertFalse(model["objective"]["roi_used_for_training"])
        self.assertIn(model["modules"]["starter_ip"]["verdict"], {"KEEP", "WATCH"})

    def test_zero_coverage_neutralizes_learned_weight(self):
        ex = opt.examples([self.row(1)])[0]
        ex["effects"]["starter_ip"]["coverage"] = 0.0
        weights = {name: 0.0 for name in opt.MODULES}
        weights["starter_ip"] = opt.MAX_WEIGHT
        h, a, hf, af = opt._weighted_runs(ex, weights)
        self.assertAlmostEqual(h, ex["base_h"], places=9)
        self.assertAlmostEqual(a, ex["base_a"], places=9)
        self.assertAlmostEqual(hf, 1.0, places=9)
        self.assertAlmostEqual(af, 1.0, places=9)
        p = opt._option_probability(ex, ex["options"][0], weights)
        self.assertAlmostEqual(p, ex["options"][0]["p0"], places=9)

    def test_walk_forward_uses_future_blocks_only_after_minimum_train(self):
        exs = opt.examples(self.rows(105))
        with patch.object(opt, "_BOOTSTRAPS", 20):
            report = opt.walk_forward(exs)
        self.assertEqual(report["status"], "ACTIVE")
        self.assertGreaterEqual(report["windows"], 1)
        self.assertEqual(report["windows_detail"][0]["train_games"], opt.MIN_GAMES)
        self.assertLessEqual(report["windows_detail"][0]["test_games"], opt.WF_TEST_GAMES)

    def test_model_is_explicitly_research_only(self):
        with patch.object(opt, "_BOOTSTRAPS", 20):
            model = opt.build_model(self.rows(75))
        self.assertTrue(model["research_only"])
        self.assertFalse(model["affects_v12_selection"])
        self.assertFalse(model["promotion"]["automatic"])


if __name__ == "__main__":
    unittest.main()
