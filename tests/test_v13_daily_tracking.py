import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import v13_daily_tracking as t
from v11 import v13_tracking_sync as sync


class TestV13DailyTracking(unittest.TestCase):
    def test_tracking_capture_close_settle_and_bands(self):
        with tempfile.TemporaryDirectory() as td:
            t.TRACK_FILE = Path(td) / "track.jsonl"
            t.REPORT_FILE = Path(td) / "report.json"
            result = {
                "game_pk": 1,
                "phase": "FINAL",
                "game": {"gameDate": "2026-08-17T20:00:00+00:00"},
                "ctx": {"home": "Home", "away": "Away"},
                "options": [
                    {"market":"ML","name":"Home","point":None,"p_baseball_calibrated":.60,"p_baseball_raw":.59,"p_market":.55,
                     "model_market_gap":.05,"p_win":.60,"p_push":0,"model_uncertainty":.03,"is_canonical_line":True,
                     "winamax_eval":{"price":1.90,"v11_price_gate":{"ev_at_price":.08,"required_price":1.75},"official_selected":False}},
                    {"market":"TOTAL","name":"Over","point":8.5,"p_baseball_calibrated":.56,"p_market":.51,
                     "p_win":.56,"p_push":0,"winamax_eval":{"price":None,"official_selected":False}},
                ]
            }
            self.assertEqual(t.capture_results([result], analyzed_at="2026-08-17T18:00:00+00:00", target_date="2026-08-17"), 2)
            state=t.fold(); self.assertEqual(len(state),2)
            ml=next(x for x in state.values() if x["market"]=="ML")
            self.assertAlmostEqual(ml["nominal_ev"],.14)
            self.assertEqual(t.observe_closing([result], analyzed_at="2026-08-17T19:50:00+00:00"), 2)
            journal_rows=[{"game_pk":1,"result_status":"FINAL","analyzed_at":"2026-08-17T18:00:00+00:00","home":"Home","away":"Away","home_score":5,"away_score":3}]
            self.assertEqual(t.settle_from_journal(journal_rows, settled_at="2026-08-17T23:00:00+00:00"), 2)
            state=t.fold(); ml=next(x for x in state.values() if x["market"]=="ML")
            self.assertEqual(ml["settled_result"],"WIN")
            self.assertAlmostEqual(ml["flat_1u_pnl"],.9)
            rep=json.loads(t.REPORT_FILE.read_text())
            self.assertEqual(rep["by_market"]["ML"]["priced"],1)
            self.assertEqual(rep["by_nominal_ev_band"]["ML"][">=10%"]["wins"],1)
            self.assertEqual(rep["by_market"]["TOTAL"]["priced"],0)

    def test_sync_from_persisted_journal_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as td:
            t.TRACK_FILE = Path(td) / "track.jsonl"
            t.REPORT_FILE = Path(td) / "report.json"
            rows=[{
                "run_id":"abc","game_pk":2,"game_date":"2026-08-17T21:00:00+00:00","analyzed_at":"2026-08-17T19:00:00+00:00",
                "target_date":"2026-08-17","home":"Home","away":"Away","phase":"FINAL",
                "options":[{"market":"ML","name":"Away","point":None,"p_baseball_calibrated":.53,"p_market":.50,"p_win":.53,"p_push":0,
                            "winamax_eval":{"price":2.02,"v11_price_gate":{"ev_at_price":.04,"required_price":1.95}}}]
            }]
            with patch.object(sync.journal,"load_rows",return_value=rows):
                self.assertEqual(sync.sync_from_journal(),1)
                self.assertEqual(sync.sync_from_journal(),0)
            state=t.fold(); self.assertEqual(len(state),1)
            item=next(iter(state.values()))
            self.assertEqual(item["source_run_id"],"abc")
            self.assertAlmostEqual(item["nominal_ev"],.0706,places=4)

    def test_band_boundaries(self):
        self.assertEqual(t._band(-.001),"<0%")
        self.assertEqual(t._band(0),"0-1%")
        self.assertEqual(t._band(.015),"1-3%")
        self.assertEqual(t._band(.04),"3-5%")
        self.assertEqual(t._band(.07),"5-10%")
        self.assertEqual(t._band(.10),">=10%")


if __name__ == "__main__":
    unittest.main()
