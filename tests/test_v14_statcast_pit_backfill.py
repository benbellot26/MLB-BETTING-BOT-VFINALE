from __future__ import annotations

import unittest

from v14.statcast_pit_backfill import build


def row(day:str,pitch:int=1,pitch_type:str="FF"):
    return {"game_date":day,"game_pk":"1","at_bat_number":"1","pitch_number":str(pitch),"batter":"101","pitcher":"202","events":"single","description":"hit_into_play","estimated_woba_using_speedangle":"0.410","launch_speed":"101","launch_speed_angle":"6","release_speed":"96","pitch_type":pitch_type}


class StatcastPitBackfillTests(unittest.TestCase):
    def test_only_prior_pitch_rows_enter_cutoff_snapshot_and_pitch_splits(self):
        def fetch(a,b,season=None):
            return [row("2026-04-01",1,"FF"),row("2026-04-01",2,"SL")],{"requests_made":1,"deduped_rows":2}
        out=build("2026-04-03",season_start="2026-04-01",fetch_chunk=fetch)
        self.assertTrue(out["point_in_time"])
        self.assertTrue(out["stable_id_only"])
        self.assertEqual(out["raw_pitch_rows"],2)
        self.assertEqual(out["priors"]["schema"],"pulsar-v14-statcast-id-priors-v2")
        self.assertIn("101",out["priors"]["hitters"])
        self.assertIn("202",out["priors"]["pitchers"])
        self.assertEqual(set(out["priors"]["hitters"]["101"]["pitch_type_splits"]),{"FF","SL"})
        self.assertGreater(out["coverage"]["hitter_pitch_split_players"],0)
        self.assertLess(out["priors"]["hitters"]["101"]["max_game_date"],out["cutoff_day"])
        self.assertFalse(out["auto_activation"])

    def test_provider_bom_on_pitch_type_header_is_normalized(self):
        def fetch(a,b,season=None):
            first=row("2026-04-01",1,"FF")
            first["\ufeffpitch_type"]=first.pop("pitch_type")
            return [first],{"requests_made":1,"deduped_rows":1}
        out=build("2026-04-03",season_start="2026-04-01",fetch_chunk=fetch)
        self.assertEqual(set(out["priors"]["hitters"]["101"]["pitch_type_splits"]),{"FF"})
        self.assertEqual(out["priors"]["pitchers"]["202"]["pitch_mix"],{"FF":1.0})
        self.assertGreater(out["coverage"]["hitter_pitch_split_players"],0)
        self.assertIn("BOM",out["header_normalization"])

    def test_current_day_or_future_row_fails_closed(self):
        def fetch(a,b,season=None):
            return [row("2026-04-03")],{}
        with self.assertRaises(ValueError):
            build("2026-04-03",season_start="2026-04-01",fetch_chunk=fetch)


if __name__=="__main__":unittest.main()