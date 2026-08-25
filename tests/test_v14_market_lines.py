import unittest

from v14.market_lines import canonical_market_snapshot, choose_total_line, complete_total_lines_by_book


def _book(key,*lines,last_update=None,markets=None):
    if markets is None:
        outcomes=[]
        for line in lines: outcomes.extend([{"name":"Over","point":line,"price":1.91},{"name":"Under","point":line,"price":1.91}])
        markets=[{"key":"totals","outcomes":outcomes}]
    out={"key":key,"markets":markets}
    if last_update is not None: out["last_update"]=last_update
    return out

class V14MarketLinesTests(unittest.TestCase):
    def test_preferred_complete_line_wins_without_price_feature(self):
        event={"bookmakers":[_book("pinnacle",8.5),_book("other",9.5)]}; out=choose_total_line(event); self.assertEqual(out["line"],8.5); self.assertEqual(out["source"],"pinnacle"); self.assertFalse(out["market_price_used_as_feature"])
    def test_modal_line_is_stable_fallback(self):
        event={"bookmakers":[_book("a",8.5),_book("b",8.5),_book("c",9.5)]}; out=choose_total_line(event); self.assertEqual(out["line"],8.5); self.assertEqual(out["books_at_line"],2)
    def test_whole_run_and_incomplete_pairs_are_rejected(self):
        event={"bookmakers":[{"key":"x","markets":[{"key":"totals","outcomes":[{"name":"Over","point":8.0,"price":1.9},{"name":"Under","point":8.0,"price":1.9},{"name":"Over","point":8.5,"price":1.9}]}]}]}
        self.assertEqual(complete_total_lines_by_book(event),{})
        with self.assertRaisesRegex(ValueError,"half-run"): choose_total_line(event)
    def test_verified_fresh_books_beat_unverified_and_stale(self):
        at="2026-08-25T18:00:00Z"; event={"bookmakers":[_book("unknown",9.5),_book("stale",10.5,last_update="2026-08-25T16:00:00Z"),_book("pinnacle",8.5,last_update="2026-08-25T17:50:00Z")]}; out=choose_total_line(event,as_of=at); self.assertEqual(out["line"],8.5); self.assertTrue(out["freshness_verified"])
    def test_future_timestamp_is_rejected(self):
        event={"bookmakers":[_book("future",8.5,last_update="2026-08-25T19:00:00Z")]}
        with self.assertRaisesRegex(ValueError,"eligible"): choose_total_line(event,as_of="2026-08-25T18:00:00Z")
    def test_unverified_timestamp_is_fallback_only(self):
        event={"bookmakers":[_book("pinnacle",8.5)]}; out=choose_total_line(event,as_of="2026-08-25T18:00:00Z"); self.assertFalse(out["freshness_verified"])
    def test_rl_snapshot_requires_complementary_pair(self):
        markets=[{"key":"spreads","outcomes":[{"name":"Home","point":-1.5,"price":2.0},{"name":"Away","point":-1.5,"price":2.1}]},{"key":"totals","outcomes":[{"name":"Over","point":8.5,"price":1.9},{"name":"Under","point":8.5,"price":1.9}]}]
        event={"home_team":"Home","away_team":"Away","bookmakers":[_book("pinnacle",last_update="2026-08-25T17:55:00Z",markets=markets)]}; snap=canonical_market_snapshot(event,total_line=8.5,as_of="2026-08-25T18:00:00Z"); self.assertNotIn("RL",snap["markets"])

if __name__=="__main__": unittest.main()
