from __future__ import annotations

import unittest

from v14.integer_totals_challenger import probabilities


class V14IntegerTotalsChallengerTests(unittest.TestCase):
    def test_integer_line_has_explicit_push_mass(self)->None:
        out=probabilities(home_mu=4.5,away_mu=4.5,total_line=9.0)
        self.assertGreater(out["push"],0.0)
        self.assertAlmostEqual(out["over"]+out["push"]+out["under"],1.0,places=10)
        self.assertFalse(out["champion_impact"])
        self.assertFalse(out["market_probability_used_as_feature"])

    def test_half_run_line_is_rejected_by_challenger(self)->None:
        with self.assertRaises(ValueError):probabilities(home_mu=4.5,away_mu=4.5,total_line=8.5)


if __name__=="__main__":unittest.main()
