from __future__ import annotations

import unittest

from v11 import v13_posterior_policy as policy


def _row(game, phase, y, baseball, market, market_name="ML"):
    return {
        "game_pk":game,
        "game_date":f"2026-07-{(game%28)+1:02d}T18:00:00Z",
        "phase":phase,
        "market":market_name,
        "settled_result":"WIN" if y else "LOSS",
        "p_baseball_calibrated":baseball,
        "p_market":market,
    }


class V13PosteriorPolicyTests(unittest.TestCase):
    def test_latest_phase_per_game_counts_each_game_once(self):
        rows=[
            _row(1,"EARLY",1,.55,.56),
            _row(1,"LATE",1,.57,.58),
            _row(1,"FINAL",1,.60,.61),
            _row(2,"EARLY",0,.45,.44),
        ]
        pooled=policy.latest_phase_per_game(rows)
        self.assertEqual(len(pooled),2)
        self.assertEqual({r["game_pk"] for r in pooled},{1,2})
        self.assertEqual(next(r for r in pooled if r["game_pk"]==1)["phase"],"FINAL")

    def test_harmful_market_selects_zero_sharp_weight(self):
        rows=[]
        for i in range(60):
            y=i%2
            baseball=.80 if y else .20
            market=.20 if y else .80
            rows.append(_row(i+1,"FINAL",y,baseball,market))
        choice=policy.select_weight(rows,minimum=30)
        self.assertEqual(choice["status"],"LEARNED_FROM_PRIOR_GAMES")
        self.assertEqual(choice["weight"],0.0)

    def test_strong_market_can_win_weight_grid(self):
        rows=[]
        for i in range(60):
            y=i%2
            baseball=.55 if y else .45
            market=.95 if y else .05
            rows.append(_row(i+1,"FINAL",y,baseball,market))
        choice=policy.select_weight(rows,minimum=30)
        self.assertEqual(choice["weight"],1.0)

    def test_resolve_weight_prefers_phase_then_market_and_falls_back_to_baseball(self):
        artifact={"entries":{
            "MARKET:ML":{"active_for_shadow":True,"weight":.25,"games":100},
            "PHASE:FINAL:ML":{"active_for_shadow":True,"weight":.40,"games":70},
        }}
        w,src,n=policy.resolve_weight(artifact,"ML","FINAL")
        self.assertEqual((w,src,n),(.40,"PHASE:FINAL:ML",70))
        w,src,n=policy.resolve_weight(artifact,"ML","EARLY")
        self.assertEqual((w,src,n),(.25,"MARKET:ML",100))
        w,src,n=policy.resolve_weight({"entries":{}},"TOTAL","FINAL")
        self.assertEqual(w,0.0)
        self.assertEqual(src,"BASEBALL_ONLY_UNTIL_VALIDATED_WEIGHT")

    def test_policy_is_shadow_only_and_phase_specific(self):
        observations=[]
        for i in range(90):
            y=i%2
            observations.append(_row(i+1,"FINAL",y,.55 if y else .45,.90 if y else .10,"TOTAL"))
        artifact=policy.build_policy(observations)
        self.assertFalse(artifact["primary_probability_affected"])
        self.assertTrue(artifact["promotion_requires_unique_games"])
        self.assertIn("MARKET:TOTAL",artifact["entries"])
        self.assertIn("PHASE:FINAL:TOTAL",artifact["entries"])
        for entry in artifact["entries"].values():
            self.assertGreaterEqual(float(entry.get("weight") or 0),0)
            self.assertLessEqual(float(entry.get("weight") or 0),1)


if __name__=="__main__":
    unittest.main()
