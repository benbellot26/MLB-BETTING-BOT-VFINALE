import unittest
from v11 import engine, selector
from v11.journal import settle_bet, settle_option

class V11Tests(unittest.TestCase):
    def test_poisson_direction(self):
        self.assertGreater(engine.prob_home_win(5.2,4.0), .5)
        self.assertLess(engine.prob_home_win(3.5,4.8), .5)
    def test_value_gate(self):
        rec={"p_effective":.60,"winamax_eval":{"price":2.0}}
        self.assertTrue(selector.value_gate(rec)["ok"])
        rec["winamax_eval"]["price"]=1.40
        self.assertFalse(selector.value_gate(rec)["ok"])
    def test_ml_settlement(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":5,"away_score":3};bet={"market":"ML","pick":"H","units":1,"winamax_price":1.8,"status":"PENDING","p_effective":.6}
        self.assertTrue(settle_bet(bet,row));self.assertEqual(bet["status"],"WIN");self.assertAlmostEqual(bet["profit_units"],.8)
    def test_runline_push(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":4,"away_score":3};opt={"market":"RUNLINE","name":"A","point":1.0,"p_effective":.55}
        settle_option(opt,row);self.assertEqual(opt["result"],"PUSH")
    def test_total_push(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":5,"away_score":4};opt={"market":"TOTAL","name":"Over","point":9.0,"p_effective":.55}
        settle_option(opt,row);self.assertEqual(opt["result"],"PUSH")

if __name__=="__main__":unittest.main()
