import unittest
from v11.validation import evaluate_probability_challenger
from v11.models import sigmoid, logit
from v11.journal import settle_bet

class V11Tests(unittest.TestCase):
    def test_math_roundtrip(self):
        for p in (.1,.3,.5,.7,.9): self.assertAlmostEqual(sigmoid(logit(p)),p,places=9)
    def test_challenger_gate_rejects_tiny_sample(self):
        r=evaluate_probability_challenger([.6]*10,[.61]*10,[1,0]*5); self.assertFalse(r["passes"])
    def test_ml_settlement(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":5,"away_score":3}; bet={"market":"ML","pick":"H","units":1,"winamax_price":1.8,"status":"PENDING"}
        self.assertTrue(settle_bet(bet,row)); self.assertEqual(bet["status"],"WIN"); self.assertAlmostEqual(bet["profit_units"],.8)
    def test_runline_push(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":4,"away_score":3}; bet={"market":"RUNLINE","pick":"A","point":1.0,"units":1,"winamax_price":1.9,"status":"PENDING"}
        self.assertTrue(settle_bet(bet,row)); self.assertEqual(bet["status"],"PUSH")
    def test_total_push(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":5,"away_score":4}; bet={"market":"TOTAL","pick":"Over","point":9.0,"units":1,"winamax_price":1.9,"status":"PENDING"}
        self.assertTrue(settle_bet(bet,row)); self.assertEqual(bet["status"],"PUSH")

if __name__=="__main__": unittest.main()
