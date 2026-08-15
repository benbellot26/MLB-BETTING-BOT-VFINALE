from __future__ import annotations

import unittest

from v11.v123_runtime import activate

activate()

from v11 import config, selector
from v11 import safe_singles_v1231 as value_selection


class ValueSelectionV1232Tests(unittest.TestCase):
    def _rec(self, price, p=.70, uncertainty=0.0, market="RUNLINE", p_market=None, p_learned=None):
        return {
            "market": market,
            "name": "Home",
            "point": 1.5 if market == "RUNLINE" else 8.5 if market == "TOTAL" else None,
            "p_effective": p,
            "p_model": p,
            "p_learned": p if p_learned is None else p_learned,
            "p_win": p,
            "p_push": 0.0,
            "p_market": p_market,
            "model_uncertainty": uncertainty,
            "reference_market": {"price": price, "best_price": price, "book": "pinnacle", "best_book": "pinnacle",
                                 "quote_count": 2, "source": "sharp_second_best"},
            "winamax_eval": {"price": 1.25},
        }

    def test_reference_price_below_140_is_rejected_even_when_model_value_is_safe(self):
        gate = selector.value_gate(self._rec(1.39, p=.85))
        self.assertTrue(gate["model_value_ok"])
        self.assertFalse(gate["price_floor_ok"])
        self.assertFalse(gate["ok"])
        self.assertAlmostEqual(gate["min_reference_price"], 1.40)

    def test_exactly_140_can_pass_but_only_with_enough_model_value(self):
        gate = selector.value_gate(self._rec(1.40, p=.85))
        self.assertTrue(gate["model_value_ok"])
        self.assertTrue(gate["price_floor_ok"])
        self.assertTrue(gate["confidence_ok"])
        self.assertTrue(gate["ok"])

    def test_runline_confidence_floor_is_55_percent(self):
        good = selector.value_gate(self._rec(2.20, p=.55, market="RUNLINE"))
        bad = selector.value_gate(self._rec(2.20, p=.549, market="RUNLINE"))
        self.assertTrue(good["confidence_ok"])
        self.assertTrue(good["ok"])
        self.assertFalse(bad["confidence_ok"])
        self.assertFalse(bad["ok"])
        self.assertAlmostEqual(good["min_confidence"], .55)

    def test_moneyline_is_more_selective_at_58_percent(self):
        bad = selector.value_gate(self._rec(2.00, p=.57, market="ML"))
        good = selector.value_gate(self._rec(2.00, p=.58, market="ML"))
        self.assertTrue(bad["model_value_ok"])
        self.assertFalse(bad["confidence_ok"])
        self.assertFalse(bad["ok"])
        self.assertTrue(good["confidence_ok"])
        self.assertTrue(good["ok"])
        self.assertAlmostEqual(good["min_confidence"], .58)

    def test_total_is_more_selective_at_58_percent(self):
        bad = selector.value_gate(self._rec(2.00, p=.57, market="TOTAL"))
        good = selector.value_gate(self._rec(2.00, p=.58, market="TOTAL"))
        self.assertFalse(bad["confidence_ok"])
        self.assertTrue(good["confidence_ok"])
        self.assertAlmostEqual(good["min_confidence"], .58)

    def test_winamax_price_does_not_control_informational_eligibility(self):
        rec = self._rec(1.80, p=.70, market="RUNLINE")
        rec["winamax_eval"]["price"] = 1.10
        gate = selector.value_gate(rec)
        self.assertTrue(gate["ok"])
        self.assertAlmostEqual(gate["price"], 1.80)
        self.assertAlmostEqual(gate["winamax_price"], 1.10)

    def test_reference_price_uses_second_best_fresh_sharp_quote_and_ignores_winamax(self):
        event = {
            "bookmakers": [
                {"key": "pinnacle", "last_update": "2026-08-15T10:00:00Z", "markets": [
                    {"key": "spreads", "last_update": "2026-08-15T10:00:00Z", "outcomes": [
                        {"name": "Home", "point": 1.5, "price": 1.80}
                    ]}
                ]},
                {"key": "betonlineag", "last_update": "2026-08-15T10:00:00Z", "markets": [
                    {"key": "spreads", "last_update": "2026-08-15T10:00:00Z", "outcomes": [
                        {"name": "Home", "point": 1.5, "price": 1.75}
                    ]}
                ]},
                {"key": "winamax_fr", "last_update": "2026-08-15T10:00:00Z", "markets": [
                    {"key": "spreads", "last_update": "2026-08-15T10:00:00Z", "outcomes": [
                        {"name": "Home", "point": 1.5, "price": 2.10}
                    ]}
                ]},
            ]
        }
        ref = value_selection._reference_market(event, {"market": "RUNLINE", "name": "Home", "point": 1.5},
                                                "2026-08-15T10:05:00Z")
        self.assertEqual(ref["quote_count"], 2)
        self.assertEqual(ref["source"], "sharp_second_best")
        self.assertEqual(ref["book"], "betonlineag")
        self.assertAlmostEqual(ref["price"], 1.75)
        self.assertAlmostEqual(ref["best_price"], 1.80)

    def test_large_sharp_disagreement_is_penalized_not_hard_rejected(self):
        dq = {"score": .90}
        rec = self._rec(2.00, p=.65, market="RUNLINE")
        gate_small = selector.value_gate({**rec, "p_market": .62, "p_learned": .65})
        gate_large = selector.value_gate({**rec, "p_market": .50, "p_learned": .65})
        self.assertTrue(gate_large["ok"])
        self.assertLess(selector._score(rec, gate_large, dq), selector._score(rec, gate_small, dq))

    def test_runtime_version_is_v1232(self):
        self.assertTrue(config.VERSION.startswith("12.3.2"))


if __name__ == "__main__":
    unittest.main()
