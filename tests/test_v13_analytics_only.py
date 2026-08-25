from __future__ import annotations

import unittest
from pathlib import Path

from v11 import v13_analytics_only as analytics


class V13AnalyticsOnlyTests(unittest.TestCase):
    def test_allocation_keeps_diagnostics_but_removes_betting_actions(self):
        option = {
            "market": "ML",
            "name": "Home",
            "selection_score": 88.0,
            "winamax_eval": {
                "price": 1.82,
                "v11_price_gate": {"price": 1.80, "ev_at_price": .05},
                "official_selected": True,
                "selected": True,
                "official_units": 1.5,
                "units": 1.5,
                "stake_eur": 15.0,
                "official_reason": "legacy selection",
            },
        }
        result = {"game_pk": 1, "options": [option]}
        chosen = [{"result": result, "rec": option}]
        combo = {"official": True, "legs": chosen, "units": .5}
        pool = [{"result": result, "rec": option, "score": 88.0}]
        portfolio = {"official_count": 1, "official_units": 1.5, "new_allocated": 15.0}

        clean_portfolio, clean_chosen, clean_combo, clean_pool = analytics.suppress_allocation(
            [result], (portfolio, chosen, combo, pool)
        )

        self.assertEqual(clean_chosen, [])
        self.assertEqual(clean_combo, {})
        self.assertIs(clean_pool, pool)
        self.assertTrue(clean_portfolio["analytics_only"])
        self.assertTrue(clean_portfolio["betting_actions_disabled"])
        self.assertEqual(clean_portfolio["official_count"], 0)
        self.assertEqual(clean_portfolio["official_units"], 0.0)
        execution = option["winamax_eval"]
        self.assertFalse(execution["official_selected"])
        self.assertFalse(execution["selected"])
        self.assertEqual(execution["official_units"], 0.0)
        self.assertEqual(execution["stake_eur"], 0.0)
        self.assertEqual(execution["price"], 1.82)
        self.assertEqual(execution["v11_price_gate"]["ev_at_price"], .05)
        self.assertEqual(execution["official_reason"], analytics.ANALYTICS_ONLY_REASON)

    def test_storage_guard_is_a_noop(self):
        self.assertEqual(analytics.disabled_record_selected_bets([{"anything": True}], {"official": True}), 0)

    def test_payload_guard_accepts_analytics_and_rejects_actionable_state(self):
        safe = {
            "chosen": [],
            "combo": {},
            "results": [{"game_pk": 1, "options": [{"winamax_eval": {"official_selected": False, "official_units": 0}}]}],
        }
        self.assertTrue(analytics.assert_payload(safe))
        with self.assertRaises(RuntimeError):
            analytics.assert_payload({"chosen": [{"bet": 1}], "combo": {}, "results": []})
        with self.assertRaises(RuntimeError):
            analytics.assert_payload({
                "chosen": [], "combo": {},
                "results": [{"game_pk": 1, "options": [{"winamax_eval": {"official_selected": True}}]}],
            })

    def test_v13_entry_wires_redundant_fail_closed_guards(self):
        text = Path("v11/v13_entry.py").read_text(encoding="utf-8")
        self.assertIn("v13_analytics_only.suppress_allocation", text)
        self.assertIn("storage.record_selected_bets = v13_analytics_only.disabled_record_selected_bets", text)
        self.assertIn("v13_analytics_only.assert_payload_file", text)
        self.assertIn("runner.send_persisted = _send_persisted_v135", text)

    def test_production_workflow_checks_v14_analytics_only_before_discord(self):
        workflow = Path(".github/workflows/mlb-bot.yml").read_text(encoding="utf-8")
        runtime = Path("v14/production_runtime.py").read_text(encoding="utf-8")
        self.assertIn("Validate Pulsar V14 publication state", workflow)
        self.assertIn("validate_production_payload(payload)", workflow)
        self.assertIn("analytics payload contains recommendations", runtime)
        self.assertIn("analytics payload contains official combo", runtime)
        self.assertIn("legacy_probability_used_for_publication", runtime)
        self.assertIn("Publish Pulsar V14 Discord analytics", workflow)
        self.assertIn("python -m v14.production_runtime --send-persisted", workflow)
        self.assertNotIn("Publish Discord recommendations", workflow)
        self.assertNotIn("v11.v13_entry", workflow)


if __name__ == "__main__":
    unittest.main()
