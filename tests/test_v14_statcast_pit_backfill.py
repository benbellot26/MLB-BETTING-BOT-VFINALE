from __future__ import annotations

import unittest

from v14.statcast_pit_backfill import build


def row(day:str,pitch:int=1):
    return {"game_date":day,"game_pk":"1","at_bat_number":"1","pitch_number":str(pitch),"batter":"101","pitcher":"202","events":"single","estimated_woba_using_speedangle":"0.410","launch_speed":"101","launch_speed_angle":"6","release_speed":"96","pitch_type":"FF"}


class StatcastPitBackfillTests(unittest.TestCase):
    def test_only_prior_pitch_rows_enter_cutoff_snapshot(self):
        def fetch(a,b,season=None):
            return [row("2026-04-01")],{"requests_made":1,"deduped_rows":1}
        out=build("2026-04-03",season_start="2026-04-01",fetch_chunk=fetch)
        self.assertTrue(out["point_in_time"])
        self.assertTrue(out["stable_id_only"])
        self.assertEqual(out["raw_pitch_rows"],1)
        self.assertIn("101",out["priors"]["hitters"])
        self.assertIn("202",out["priors"]["pitchers"])
        self.assertLess(out["priors"]["hitters"]["101"]["max_game_date"],out["cutoff_day"])
        self.assertFalse(out["auto_activation"])

    def test_current_day_or_future_row_fails_closed(self):
        def fetch(a,b,season=None):
            return [row("2026-04-03")],{}
        with self.assertRaises(ValueError):
            build("2026-04-03",season_start="2026-04-01",fetch_chunk=fetch)


if __name__=="__main__":unittest.main()
