from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from v11 import v13_production_gate as gate


class V138ProductionChangeGateTests(unittest.TestCase):
    def _game(self,starter=1):
        return {"gamePk":7,"gameDate":"2026-08-19T19:00:00Z","teams":{"home":{"probablePitcher":{"id":starter}},"away":{"probablePitcher":{"id":2}}}}

    def test_sent_game_reopens_when_probable_starter_changes(self):
        delivered={"games":{"7":{"sent":True,"personnel_state":{"home_starter":"1","away_starter":"2","home_lineup":[],"away_lineup":[]}}}}
        with patch.object(gate.core,"phase_for_game",return_value="FINAL"):
            r=gate.build(datetime(2026,8,19,18,0,tzinfo=timezone.utc),[self._game(99)],delivered)
        self.assertTrue(r["run_needed"]);self.assertEqual(r["undelivered_final_games"][0]["reason"],"critical-personnel-change")

    def test_sent_game_reopens_when_free_live_feed_lineup_personnel_changes(self):
        delivered={"games":{"7":{"sent":True,"personnel_state":{"home_starter":"1","away_starter":"2",
                   "home_lineup":[str(x) for x in range(10,19)],"away_lineup":[str(x) for x in range(20,29)]}}}}
        feed={"liveData":{"boxscore":{"teams":{"home":{"battingOrder":[10,11,12,13,14,15,16,17,99]},
              "away":{"battingOrder":list(range(20,29))}}}}}
        with patch.object(gate.core,"phase_for_game",return_value="FINAL"),patch.object(gate.core,"mlb",return_value=feed):
            r=gate.build(datetime(2026,8,19,18,0,tzinfo=timezone.utc),[self._game(1)],delivered)
        self.assertTrue(r["run_needed"]);self.assertIn("LINEUP_PERSONNEL_CHANGED",r["undelivered_final_games"][0]["change"]["reason"])

    def test_empty_old_signature_does_not_create_false_reopen(self):
        delivered={"games":{"7":{"sent":True}}}
        with patch.object(gate.core,"phase_for_game",return_value="FINAL"):
            r=gate.build(datetime(2026,8,19,18,0,tzinfo=timezone.utc),[self._game(99)],delivered)
        self.assertFalse(r["run_needed"])

    def test_name_vs_id_starter_representation_is_not_a_false_change(self):
        delivered={"games":{"7":{"sent":True,"personnel_state":{"home_starter":"Gerrit Cole","away_starter":"2","home_lineup":[],"away_lineup":[]}}}}
        with patch.object(gate.core,"phase_for_game",return_value="FINAL"):
            r=gate.build(datetime(2026,8,19,18,0,tzinfo=timezone.utc),[self._game(543037)],delivered)
        self.assertFalse(r["run_needed"])


if __name__=="__main__":unittest.main()
