from __future__ import annotations

import unittest

from v14.distribution import negative_binomial_pmf, probability_surface
from v14.model import ProbabilitySurface, RunProjection
from v14.shadow import build_shadow, projection_from_v13_result
from v14.validation import score_surface


class V14FoundationTests(unittest.TestCase):
    def _projection(self, home_mu=4.5, away_mu=4.5, total_line=8.5):
        return RunProjection(
            game_pk="1", game_date="2026-08-20T23:00:00Z", analyzed_at="2026-08-20T20:00:00Z",
            home="Home", away="Away", home_mu=home_mu, away_mu=away_mu,
            total_line=total_line, dispersion=7.5, phase="FINAL", source_generation="v13-test",
        )

    def _v13_result(self):
        return {
            "game_pk": 1,
            "game": {"gameDate": "2026-08-20T23:00:00Z"},
            "analyzed_at": "2026-08-20T20:00:00Z",
            "phase": "FINAL",
            "model_generation": "v13-test",
            "ctx": {"home": "Home", "away": "Away"},
            "hmu": 4.7,
            "amu": 4.1,
            "options": [
                {"market": "ML", "name": "Home", "p_predictive_final": .99, "p_market": .01},
                {"market": "ML", "name": "Away", "p_predictive_final": .01, "p_market": .99},
                {"market": "TOTAL", "name": "Over", "point": 8.5, "is_canonical_line": True,
                 "p_predictive_final": .99, "p_market": .01},
                {"market": "TOTAL", "name": "Under", "point": 8.5, "is_canonical_line": True,
                 "p_predictive_final": .01, "p_market": .99},
            ],
        }

    def test_negative_binomial_mean_is_preserved(self):
        pmf, tail = negative_binomial_pmf(4.6, 7.5)
        mean = sum(k * p for k, p in enumerate(pmf))
        self.assertLess(tail, 1e-7)
        self.assertAlmostEqual(mean, 4.6, places=5)
        self.assertAlmostEqual(sum(pmf), 1.0, places=12)

    def test_equal_run_means_produce_neutral_moneyline(self):
        surface, _ = probability_surface(self._projection())
        self.assertAlmostEqual(surface.home_ml, .5, places=12)
        self.assertAlmostEqual(surface.away_ml, .5, places=12)

    def test_one_distribution_produces_four_complementary_pairs(self):
        surface, _ = probability_surface(self._projection(home_mu=5.0, away_mu=3.8))
        surface.validated()
        self.assertAlmostEqual(surface.home_ml + surface.away_ml, 1.0, places=12)
        self.assertAlmostEqual(surface.home_minus_1_5 + surface.away_plus_1_5, 1.0, places=12)
        self.assertAlmostEqual(surface.home_plus_1_5 + surface.away_minus_1_5, 1.0, places=12)
        self.assertAlmostEqual(surface.over + surface.under, 1.0, places=12)

    def test_higher_home_run_mean_increases_home_win_probability(self):
        low, _ = probability_surface(self._projection(home_mu=4.0, away_mu=4.2))
        high, _ = probability_surface(self._projection(home_mu=5.0, away_mu=4.2))
        self.assertGreater(high.home_ml, low.home_ml)
        self.assertGreater(high.home_minus_1_5, low.home_minus_1_5)

    def test_display_total_requires_half_run_line(self):
        with self.assertRaises(ValueError):
            self._projection(total_line=8.0).validated()

    def test_v13_adapter_reads_only_run_means_not_v13_or_market_probabilities(self):
        result = self._v13_result()
        first = build_shadow(result)
        result["options"][0]["p_predictive_final"] = .02
        result["options"][0]["p_market"] = .98
        result["options"][2]["p_predictive_final"] = .03
        result["options"][2]["p_market"] = .97
        second = build_shadow(result)
        self.assertEqual(first["probabilities"], second["probabilities"])
        self.assertFalse(first["market_probability_used_as_feature"])
        self.assertFalse(first["affects_production"])
        self.assertEqual(first["role"], "SHADOW_ONLY")

    def test_v13_adapter_rejects_post_start_snapshot(self):
        result = self._v13_result()
        result["analyzed_at"] = "2026-08-21T00:00:00Z"
        with self.assertRaises(ValueError):
            projection_from_v13_result(result)

    def test_validation_scores_only_four_independent_targets(self):
        surface = ProbabilitySurface(
            away_ml=.4, home_ml=.6,
            away_plus_1_5=.7, home_minus_1_5=.3,
            away_minus_1_5=.2, home_plus_1_5=.8,
            over=.55, under=.45,
        )
        report = score_surface(surface, home_score=5, away_score=3, total_line=8.5)
        self.assertEqual(set(report["targets"]), {"home_ml", "home_minus_1_5", "home_plus_1_5", "over"})
        self.assertEqual(len(report["targets"]), 4)


if __name__ == "__main__":
    unittest.main()
