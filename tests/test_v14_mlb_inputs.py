import unittest

from v14.mlb_inputs import build_game_inputs, effective_lineup_ops


class FakeMLB:
    def __call__(self,url,params):
        if url.endswith("/v1/teams/stats"):
            group=params.get("group")
            if group=="hitting": return {"stats":[{"splits":[{"stat":{"runsPerGame":4.5,"ops":.720}},{"stat":{"runsPerGame":4.4,"ops":.710}}]}]}
            return {"stats":[{"splits":[{"stat":{"era":4.2,"whip":1.30}},{"stat":{"era":4.3,"whip":1.31}}]}]}
        if "/v1/teams/1/stats" in url:
            stat={"runsPerGame":4.8,"ops":.760} if params.get("group")=="hitting" else {"era":3.9,"whip":1.22}; return {"stats":[{"splits":[{"stat":stat}]}]}
        if "/v1/teams/2/stats" in url:
            stat={"runsPerGame":4.2,"ops":.690} if params.get("group")=="hitting" else {"era":4.6,"whip":1.38}; return {"stats":[{"splits":[{"stat":stat}]}]}
        if "/v1/people/101/stats" in url:
            if params.get("stats")=="yearByYear": return {"stats":[{"splits":[{"season":"2025","stat":{"inningsPitched":"130","era":"3.70","whip":"1.20","strikeoutsPer9Inn":"9.0","walksPer9Inn":"2.8","homeRunsPer9":"1.0"}},{"season":"2024","stat":{"inningsPitched":"120","era":"3.90","whip":"1.24","strikeoutsPer9Inn":"8.7","walksPer9Inn":"3.0","homeRunsPer9":"1.1"}}]}]}
            return {"stats":[{"splits":[{"stat":{"inningsPitched":"100","era":"3.60","whip":"1.18","strikeoutsPer9Inn":"9.2","walksPer9Inn":"2.7","homeRunsPer9":"0.9"}}]}]}
        if "/v1/people/202/stats" in url:
            if params.get("stats")=="yearByYear": return {"stats":[{"splits":[{"season":"2025","stat":{"inningsPitched":"125","era":"4.50","whip":"1.35","strikeoutsPer9Inn":"7.8","walksPer9Inn":"3.4","homeRunsPer9":"1.3"}},{"season":"2024","stat":{"inningsPitched":"110","era":"4.70","whip":"1.40","strikeoutsPer9Inn":"7.5","walksPer9Inn":"3.6","homeRunsPer9":"1.4"}}]}]}
            return {"stats":[{"splits":[{"stat":{"inningsPitched":"90","era":"4.80","whip":"1.42","strikeoutsPer9Inn":"7.4","walksPer9Inn":"3.7","homeRunsPer9":"1.5"}}]}]}
        if "/v1/people/" in url and params.get("group")=="hitting":
            pid=int(url.split("/people/")[1].split("/")[0]); return {"stats":[{"splits":[{"stat":{"ops":str(.680+(pid%9)*.012)}}]}]}
        if url.endswith("/v1/game/123/boxscore"):
            def team(start):
                players={}
                for idx in range(9):
                    pid=start+idx; players[f"ID{pid}"]={"battingOrder":str((idx+1)*100),"person":{"id":pid,"fullName":f"H{pid}"}}
                return {"players":players}
            return {"teams":{"home":team(301),"away":team(401)}}
        if url.endswith("/v1/schedule"): return {"dates":[]}
        raise AssertionError(f"Unexpected MLB request {url} {params}")


class V14MLBInputsTests(unittest.TestCase):
    def test_partial_lineup_ops_is_shrunk_to_team_baseline(self):
        effective,confidence=effective_lineup_ops({"count":5,"weighted_ops":.900},.700); self.assertAlmostEqual(confidence,.2); self.assertAlmostEqual(effective,.740)
        effective9,confidence9=effective_lineup_ops({"count":9,"weighted_ops":.800},.700); self.assertEqual(confidence9,1.0); self.assertEqual(effective9,.800)
        base,conf=effective_lineup_ops({"count":4,"weighted_ops":.950},.700); self.assertEqual(conf,0.0); self.assertEqual(base,.700)

    def test_builds_native_structural_and_safe_feature_row(self):
        game={"gamePk":123,"gameDate":"2026-08-25T23:00:00Z","venue":{"name":"Unknown Test Park"},"teams":{"home":{"team":{"id":1,"name":"New York Yankees"},"probablePitcher":{"id":101,"fullName":"Home SP"}},"away":{"team":{"id":2,"name":"Boston Red Sox"},"probablePitcher":{"id":202,"fullName":"Away SP"}}}}
        native=build_game_inputs(game,target_date="2026-08-25",analyzed_at="2026-08-25T18:00:00Z",getter=FakeMLB())
        self.assertEqual(native.structural.game_pk,"123"); self.assertGreater(native.structural.structural_home_mu,1.8); self.assertGreater(native.structural.structural_away_mu,1.8); self.assertEqual(native.structural.static_park_factor,1.03); self.assertTrue(native.feature_row["point_in_time"]); self.assertEqual(native.feature_row["point_in_time_validation_reasons"],[]); self.assertEqual(native.feature_row["context"]["home_lineup"]["count"],9); self.assertEqual(native.feature_row["context"]["away_starter"]["name"],"Away SP"); self.assertTrue(native.feature_row["data_quality"]["starter_complete"]); self.assertEqual(native.feature_row["data_quality"]["home_lineup_structural_confidence"],1.0)

if __name__=="__main__": unittest.main()
