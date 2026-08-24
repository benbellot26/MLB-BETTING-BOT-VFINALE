from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import v13_daily_tracking as tracking


class V1310ManualRunCaptureTests(unittest.TestCase):
    def test_same_manual_run_snapshot_can_become_t60_without_paid_poll(self):
        at = "2026-08-24T19:00:00+00:00"
        result = {
            "game_pk": 1,
            "game": {"gameDate": "2026-08-24T20:00:00+00:00"},
            "as_of": at,
            "phase": "LATE",
            "ctx": {"home": "Home", "away": "Away"},
            "options": [{
                "market": "ML",
                "name": "Home",
                "point": None,
                "is_canonical_line": True,
                "p_baseball_calibrated": 0.60,
                "p_predictive_final": 0.60,
                "p_effective": 0.60,
                "p_market": 0.57,
                "p_win": 0.60,
                "p_push": 0.0,
                "winamax_eval": {"price": 1.90},
                "data_quality": 0.90,
            }],
        }
        with tempfile.TemporaryDirectory() as td, \
             patch.object(tracking, "TRACK_FILE", Path(td) / "tracking.jsonl"), \
             patch.object(tracking, "REPORT_FILE", Path(td) / "report.json"), \
             patch.object(tracking.core, "odds_api", side_effect=AssertionError("paid poll must not run")) as paid:
            self.assertEqual(tracking.capture_results([result], analyzed_at=at, target_date="2026-08-24"), 1)
            self.assertEqual(tracking.observe_closing([result], analyzed_at=at), 1)
            paid.assert_not_called()
            states = list(tracking.fold().values())

        self.assertEqual(len(states), 1)
        state = states[0]
        self.assertEqual(state["observation_phase"], "LATE")
        self.assertEqual(state["t60_price"], 1.90)
        self.assertEqual(state["t60_sharp_fair"], 0.57)
        self.assertEqual(state["market_poll_reason"], "t60")

    def test_champion_allocator_captures_current_snapshot_before_checkpoint_binding(self):
        text = Path("v11/v13_entry.py").read_text(encoding="utf-8")
        start = text.index("def _tracked_allocate")
        end = text.index("\ndef _tracked_update_clv", start)
        block = text[start:end]
        self.assertIn("v13_daily_tracking.capture_results", block)
        self.assertIn("v13_daily_tracking.observe_closing", block)
        self.assertIn("v13_daily_tracking.write_report", block)
        self.assertLess(block.index("capture_results"), block.index("observe_closing"))
        self.assertNotIn("odds_api", block)


if __name__ == "__main__":
    unittest.main()
