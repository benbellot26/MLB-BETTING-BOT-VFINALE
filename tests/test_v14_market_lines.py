import unittest

from v14.market_lines import choose_total_line, complete_total_lines_by_book


def _book(key, *lines):
    outcomes = []
    for line in lines:
        outcomes.extend([
            {"name": "Over", "point": line, "price": 1.91},
            {"name": "Under", "point": line, "price": 1.91},
        ])
    return {"key": key, "markets": [{"key": "totals", "outcomes": outcomes}]}


class V14MarketLinesTests(unittest.TestCase):
    def test_preferred_complete_line_wins_without_price_feature(self):
        event = {"bookmakers": [_book("pinnacle", 8.5), _book("other", 9.5)]}
        out = choose_total_line(event)
        self.assertEqual(out["line"], 8.5)
        self.assertEqual(out["source"], "pinnacle")
        self.assertFalse(out["market_price_used_as_feature"])

    def test_modal_line_is_stable_fallback(self):
        event = {"bookmakers": [_book("a", 8.5), _book("b", 8.5), _book("c", 9.5)]}
        out = choose_total_line(event)
        self.assertEqual(out["line"], 8.5)
        self.assertEqual(out["books_at_line"], 2)

    def test_whole_run_and_incomplete_pairs_are_rejected(self):
        event = {"bookmakers": [{"key": "x", "markets": [{"key": "totals", "outcomes": [
            {"name": "Over", "point": 8.0, "price": 1.9},
            {"name": "Under", "point": 8.0, "price": 1.9},
            {"name": "Over", "point": 8.5, "price": 1.9},
        ]}]}]}
        self.assertEqual(complete_total_lines_by_book(event), {})
        with self.assertRaisesRegex(ValueError, "half-run"):
            choose_total_line(event)


if __name__ == "__main__":
    unittest.main()
