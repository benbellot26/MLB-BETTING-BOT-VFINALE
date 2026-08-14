import unittest
from v11 import engine, selector, journal, market, core

class V11StandaloneTests(unittest.TestCase):
    def test_home_win_moves_with_run_edge(self):
        self.assertGreater(engine.prob_home_win(5.0,4.0), .5)
        self.assertLess(engine.prob_home_win(4.0,5.0), .5)

    def test_negative_binomial_matrix_normalized(self):
        hp, ap = engine.score_matrix(4.6, 4.1)
        self.assertAlmostEqual(sum(hp), 1.0, places=9)
        self.assertAlmostEqual(sum(ap), 1.0, places=9)
        self.assertTrue(all(x >= 0 for x in hp + ap))

    def test_runline_complement_and_push(self):
        hw, hp = engine.prob_cover_parts(4.5, 4.0, "home", -1.0)
        aw, ap = engine.prob_cover_parts(4.5, 4.0, "away", 1.0)
        self.assertAlmostEqual(hp, ap, places=9)
        self.assertAlmostEqual(hw + aw + hp, 1.0, places=6)

    def test_total_complement_and_push(self):
        ow, op = engine.prob_total_parts(4.5, 4.0, "over", 9.0)
        uw, up = engine.prob_total_parts(4.5, 4.0, "under", 9.0)
        self.assertAlmostEqual(op, up, places=9)
        self.assertAlmostEqual(ow + uw + op, 1.0, places=6)

    def test_price_gate_accounts_for_push(self):
        rec={"p_effective":.60,"p_win":.54,"p_push":.10,"winamax_eval":{"price":2.0}}
        req=selector.required_price(rec)
        self.assertGreater(req,1.0)
        gate=selector.value_gate(rec)
        self.assertIn("ev_at_price",gate)
        self.assertAlmostEqual(gate["p_push"],.10)

    def test_settlement_pushes(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":4,"away_score":3}
        rl={"market":"RUNLINE","name":"A","point":1.0,"p_effective":.55}
        journal.settle_option(rl,row)
        self.assertEqual(rl["result"],"PUSH")
        total={"market":"TOTAL","name":"Over","point":7.0,"p_effective":.55}
        journal.settle_option(total,row)
        self.assertEqual(total["result"],"PUSH")

    def test_spread_devig_uses_opposite_points(self):
        event={"bookmakers":[{"key":"pinnacle","markets":[{"key":"spreads","outcomes":[
            {"name":"H","point":-1.5,"price":2.00},{"name":"A","point":1.5,"price":1.90}
        ]}]}]}
        old=set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS={"pinnacle"}
            h=market.sharp_consensus(event,"RUNLINE","H",-1.5)
            a=market.sharp_consensus(event,"RUNLINE","A",1.5)
            self.assertEqual(h["n"],1)
            self.assertEqual(a["n"],1)
            self.assertAlmostEqual(h["p"]+a["p"],1.0,places=9)
        finally:
            core.SHARP_BOOKS=old

    def test_ml_settlement(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":5,"away_score":3}
        bet={"market":"ML","pick":"H","units":1,"winamax_price":1.8,"status":"PENDING","p_effective":.6}
        self.assertTrue(journal.settle_bet(bet,row))
        self.assertEqual(bet["status"],"WIN")
        self.assertAlmostEqual(bet["profit_units"],.8)

if __name__=="__main__":
    unittest.main()
