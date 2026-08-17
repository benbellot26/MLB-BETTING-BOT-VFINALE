from __future__ import annotations

import unittest

from v11 import calibration_baseball_v13 as cal
from v11 import config
from v11 import uncertainty_v13
from v11 import v13_daily_tracking as tracking


class V13PrecisionHardeningTests(unittest.TestCase):
    def test_phase_is_preserved_without_inflating_market_sample(self):
        rows=[
            {"game_pk":"1","phase":"EARLY","game_date":"2026-06-01T20:00:00Z","analyzed_at":"2026-06-01T10:00:00Z",
             "options":[{"market":"ML","name":"Home","point":None,"p_baseball_raw":.55,"result":"WIN"}]},
            {"game_pk":"1","phase":"FINAL","game_date":"2026-06-01T20:00:00Z","analyzed_at":"2026-06-01T19:30:00Z",
             "options":[{"market":"ML","name":"Home","point":None,"p_baseball_raw":.61,"result":"WIN"}]},
        ]
        buckets=cal.examples_from_rows(rows)
        self.assertEqual(len(buckets["MARKET:ML"]),1)
        self.assertAlmostEqual(buckets["MARKET:ML"][0][0],.61)
        self.assertEqual(len(buckets["PHASE:EARLY:ML"]),1)
        self.assertEqual(len(buckets["PHASE:FINAL:ML"]),1)

    def test_identity_evidence_prefers_same_phase(self):
        model={"calibrators":{"MARKET:ML":{"n":40},"PHASE:FINAL:ML":{"n":7}}}
        _,source,n=cal.calibrate(.61,"ML","FINAL",model)
        self.assertEqual(source,"identity")
        self.assertEqual(n,7)

    def test_lower_data_quality_widens_interval(self):
        strong=uncertainty_v13.empirical_interval(.55,calibration_n=30,phase_n=30,market_n=40,data_quality=.95)
        weak=uncertainty_v13.empirical_interval(.55,calibration_n=30,phase_n=30,market_n=40,data_quality=.55)
        self.assertGreaterEqual(weak["sigma"],strong["sigma"])
        self.assertEqual(strong["evidence_scope"],"phase")

    def test_missing_market_poll_does_not_erase_valid_close(self):
        events=[
            {"tracking_key":"k","close_price":1.92,"close_sharp_fair":.54,"close_observed_at":"a"},
            tracking._market_update("k",{},"b",5.0,None,None),
        ]
        state=tracking.fold(events)["k"]
        self.assertEqual(state["close_price"],1.92)
        self.assertEqual(state["close_sharp_fair"],.54)
        self.assertEqual(state["close_observed_at"],"a")

    def test_closing_window_covers_scheduler_cadence(self):
        self.assertGreaterEqual(config.CLOSING_CANDIDATE_WINDOW_MIN,15)


if __name__ == "__main__":
    unittest.main()
