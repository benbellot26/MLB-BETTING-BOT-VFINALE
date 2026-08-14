from __future__ import annotations

import unittest

from v11.v123_runtime import activate

activate()

from v11 import config, selector


class SafeSinglesV1231Tests(unittest.TestCase):
    def _rec(self, price, p=.70, uncertainty=0.0):
        return {
            "p_effective": p,
            "p_model": p,
            "p_win": p,
            "p_push": 0.0,
            "model_uncertainty": uncertainty,
            "winamax_eval": {"price": price},
        }

    def test_safe_price_below_160_is_not_officially_eligible(self):
        gate = selector.value_gate(self._rec(1.59, p=.70))
        self.assertTrue(gate["model_value_ok"])
        self.assertFalse(gate["price_floor_ok"])
        self.assertFalse(gate["ok"])
        self.assertAlmostEqual(gate["min_official_single_price"], 1.60)

    def test_exactly_160_still_has_to_pass_the_full_value_gate(self):
        gate = selector.value_gate(self._rec(1.60, p=.70))
        self.assertTrue(gate["model_value_ok"])
        self.assertTrue(gate["price_floor_ok"])
        self.assertTrue(gate["ok"])

    def test_160_is_rejected_when_model_safety_is_insufficient(self):
        gate = selector.value_gate(self._rec(1.60, p=.60))
        self.assertFalse(gate["model_value_ok"])
        self.assertTrue(gate["price_floor_ok"])
        self.assertFalse(gate["ok"])
        self.assertGreater(gate["required_price"], 1.60)

    def test_floor_is_additive_not_a_probability_override(self):
        gate = selector.value_gate(self._rec(1.80, p=.55, uncertainty=.05))
        self.assertTrue(gate["price_floor_ok"])
        self.assertFalse(gate["model_value_ok"])
        self.assertFalse(gate["ok"])


if __name__ == "__main__":
    unittest.main()
