from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from v11 import v13_research_gate as gate


class V13ResearchGateTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,8,18,12,0,tzinfo=timezone.utc)

    def _game(self,gid,hours):
        return {"gamePk":gid,"gameDate":(self.now+timedelta(hours=hours)).isoformat().replace("+00:00","Z")}

    def test_missing_early_phase_requires_paid_run(self):
        report=gate.build(now=self.now,games=[self._game(1,6)],rows=[])
        self.assertTrue(report["run_needed"])
        self.assertTrue(report["paid_odds_api_required"])
        self.assertEqual(report["missing_game_phases"][0]["phase"],"EARLY")

    def test_already_captured_current_phase_skips_paid_run(self):
        rows=[{"game_pk":1,"phase":"EARLY","analyzed_at":self.now.isoformat(),
               "game_date":(self.now+timedelta(hours=6)).isoformat()}]
        with patch.object(gate.contract,"row_is_predictively_compatible",return_value=True):
            report=gate.build(now=self.now,games=[self._game(1,6)],rows=rows)
        self.assertFalse(report["run_needed"])
        self.assertFalse(report["paid_odds_api_required"])

    def test_new_phase_requires_new_snapshot(self):
        rows=[{"game_pk":1,"phase":"EARLY","analyzed_at":(self.now-timedelta(hours=2)).isoformat(),
               "game_date":(self.now+timedelta(hours=4)).isoformat()}]
        with patch.object(gate.contract,"row_is_predictively_compatible",return_value=True):
            report=gate.build(now=self.now,games=[self._game(1,4)],rows=rows)
        self.assertTrue(report["run_needed"])
        self.assertEqual(report["missing_game_phases"][0]["phase"],"LATE")

    def test_past_games_never_trigger_paid_run(self):
        report=gate.build(now=self.now,games=[self._game(1,-1)],rows=[])
        self.assertFalse(report["run_needed"])
        self.assertEqual(report["future_games"],0)


if __name__=="__main__":
    unittest.main()
