from __future__ import annotations

import unittest

from v14.exchange_microstructure import credential_status, normalize_betfair_market_book, normalize_matchbook_market


class ExchangeMicrostructureTests(unittest.TestCase):
    def test_matchbook_back_lay_depth(self):
        payload={"id":11,"name":"Moneyline","runners":[
            {"id":1,"name":"Home","volume":1000,"prices":[{"side":"back","decimal-odds":2.10,"available-amount":100},{"side":"back","decimal-odds":2.08,"available-amount":50},{"side":"lay","decimal-odds":2.12,"available-amount":120}]},
            {"id":2,"name":"Away","volume":900,"prices":[{"side":"back","decimal-odds":1.90,"available-amount":80},{"side":"lay","decimal-odds":1.92,"available-amount":110}]},
        ]}
        out=normalize_matchbook_market(payload,commission_rate=.02)
        self.assertEqual(out["status"],"READY_BENCHMARK")
        self.assertEqual(out["runners"][0]["best_back"]["price"],2.10)
        self.assertEqual(out["runners"][0]["best_lay"]["price"],2.12)
        self.assertEqual(out["runners"][0]["back_depth"],150)
        self.assertAlmostEqual(out["runners"][0]["commission_adjusted_back_price"],2.078)
        self.assertFalse(out["champion_impact"])

    def test_betfair_delayed_data_cannot_be_live_benchmark(self):
        payload={"marketId":"1.234","isMarketDataDelayed":True,"status":"OPEN","totalMatched":5000,"runners":[
            {"selectionId":1,"totalMatched":2500,"ex":{"availableToBack":[{"price":2.0,"size":100}],"availableToLay":[{"price":2.02,"size":120}]}},
            {"selectionId":2,"totalMatched":2500,"ex":{"availableToBack":[{"price":1.98,"size":90}],"availableToLay":[{"price":2.0,"size":100}]}},
        ]}
        out=normalize_betfair_market_book(payload,selection_names={"1":"Home","2":"Away"},commission_rate=.02)
        self.assertEqual(out["status"],"DELAYED_RESEARCH")
        self.assertTrue(out["market_data_delayed"])
        self.assertEqual(out["complete_two_sided_runners"],2)

    def test_credentials_are_runtime_only(self):
        out=credential_status({"MATCHBOOK_SESSION_TOKEN":"token"})
        self.assertTrue(out["matchbook_ready"])
        self.assertFalse(out["betfair_ready"])
        self.assertTrue(out["credentials_must_not_be_committed"])


if __name__=="__main__":
    unittest.main()
