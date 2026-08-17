import tempfile, unittest
from pathlib import Path

from v11 import v13_daily_postmortem as p
from v11 import v13_daily_tracking as t


class TestV13DailyPostmortem(unittest.TestCase):
    def test_independent_scoring_and_official_pnl(self):
        with tempfile.TemporaryDirectory() as td:
            t.TRACK_FILE=Path(td)/"track.jsonl"; p.OUT=Path(td)/"daily.json"
            events=[]
            base={"target_date":"2026-08-16","game_pk":1,"home":"Home","away":"Away","market":"ML","point":None,"winamax_price":2.0}
            events.append({**base,"tracking_key":"h","pick":"Home","p_model":.60,"p_market":.55,"official_selected":True,"settled_result":"WIN","flat_1u_pnl":1.0})
            events.append({**base,"tracking_key":"a","pick":"Away","p_model":.40,"p_market":.45,"official_selected":False,"settled_result":"LOSS","flat_1u_pnl":-1.0})
            t._append(events)
            r=p.build("2026-08-16")
            ml=r["markets"]["ML"]
            self.assertEqual(ml["independent_targets"],1)
            self.assertEqual(ml["model"]["n"],1)
            self.assertAlmostEqual(ml["model"]["brier"],.16)
            self.assertEqual(ml["selected"]["n"],1)
            self.assertAlmostEqual(r["official_pnl_1u"],1.0)

    def test_total_prefers_over_without_outcome_selection(self):
        rows=[
            {"game_pk":2,"market":"TOTAL","point":8.5,"pick":"Under","settled_result":"WIN","p_model":.48},
            {"game_pk":2,"market":"TOTAL","point":8.5,"pick":"Over","settled_result":"LOSS","p_model":.52},
        ]
        chosen=p._choose_independent(rows)
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]["pick"],"Over")


if __name__=="__main__":unittest.main()
