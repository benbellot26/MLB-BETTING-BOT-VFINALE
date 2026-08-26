from __future__ import annotations

import unittest

from v14.team_history_shadow import build_from_games, matchup


def game(pk:int,official:str,home_id:int,away_id:int,hs:int,aws:int,final:bool=True):
    return {"gamePk":pk,"gameDate":f"{official}T20:00:00Z","officialDate":official,"gameType":"R","status":{"abstractGameState":"Final" if final else "Preview"},"teams":{"home":{"team":{"id":home_id},"score":hs},"away":{"team":{"id":away_id},"score":aws}}}

class V14TeamHistoryShadowTests(unittest.TestCase):
    def test_same_day_final_is_excluded_for_historical_parity(self):
        games=[game(1,"2026-08-24",1,2,5,3),game(2,"2026-08-25",1,2,8,1)]
        out=build_from_games(games,"2026-08-25")
        self.assertEqual(out["accepted_prior_games"],1)
        self.assertEqual(out["same_day_games_excluded"],1)
        self.assertEqual(out["teams"]["1"]["season_to_date"]["runs_for_pg"],5.0)

    def test_nonfinal_and_nonregular_games_do_not_enter_history(self):
        regular=game(1,"2026-08-20",1,2,4,2)
        preview=game(2,"2026-08-21",1,2,9,0,final=False)
        spring=game(3,"2026-08-22",1,2,9,0); spring["gameType"]="S"
        out=build_from_games([regular,preview,spring],"2026-08-25")
        self.assertEqual(out["accepted_prior_games"],1)
        self.assertEqual(out["teams"]["2"]["season_to_date"]["runs_against_pg"],4.0)

    def test_matchup_is_shadow_only(self):
        out=build_from_games([game(1,"2026-08-20",1,2,4,2)],"2026-08-25")
        row=matchup(out,1,2)
        self.assertEqual(row["status"],"READY_SHADOW")
        self.assertFalse(row["champion_impact"])
        self.assertTrue(row["point_in_time"])

if __name__=="__main__": unittest.main()
