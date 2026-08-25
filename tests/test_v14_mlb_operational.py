import unittest

from v14.mlb_inputs import _recent_completed_games, bullpen_three_day_snapshot


class V14MLBOperationalTests(unittest.TestCase):
    def test_same_day_completed_game_is_visible_to_later_game(self):
        def getter(url,params):
            if url.endswith("/v1/schedule") and params.get("date")=="2026-08-25":
                return {"dates":[{"games":[{"gamePk":10,"gameDate":"2026-08-25T17:00:00Z","status":{"abstractGameState":"Final"}}]}]}
            if url.endswith("/v1/schedule"): return {"dates":[]}
            raise AssertionError((url,params))
        games=_recent_completed_games(1,"2026-08-25",current_game_pk=11,current_game_date="2026-08-25T22:00:00Z",getter=getter)
        self.assertEqual([g["gamePk"] for g in games],[10])

    def test_bulk_relief_workload_is_marked(self):
        game={"gamePk":10}
        def getter(url,params):
            if url.endswith("/v1/game/10/boxscore"):
                return {"teams":{"home":{"team":{"id":1},"pitchers":[100,101,102],"players":{"ID100":{"person":{"id":100},"stats":{"pitching":{"gamesStarted":1,"pitchesThrown":30}}},"ID101":{"person":{"id":101,"fullName":"Bulk"},"stats":{"pitching":{"gamesStarted":0,"pitchesThrown":48}}},"ID102":{"person":{"id":102,"fullName":"Relief"},"stats":{"pitching":{"gamesStarted":0,"pitchesThrown":12}}}}},"away":{"team":{"id":2}}}}
            raise AssertionError((url,params))
        snap=bullpen_three_day_snapshot(1,[game],getter=getter); bulk=next(r for r in snap["relievers"] if r["id"]==101); self.assertTrue(bulk["bulk_workload"]); self.assertTrue(bulk["taxed"])

if __name__=="__main__": unittest.main()
