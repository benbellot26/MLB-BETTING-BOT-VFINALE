from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from v11.v123_runtime import activate

activate()

from v11 import config, core, market
from v11 import engine_v12 as engine
from v11 import alternate_runlines_v1231 as alt


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def book(key, markets, updated):
    return {"key": key, "last_update": iso(updated), "markets": markets}


class AlternateRunLineTests(unittest.TestCase):
    def test_alternate_runlines_remain_active_in_v1232(self):
        self.assertTrue(config.VERSION.startswith("12.3.2"))

    def test_fresh_winamax_reverse_runline_is_executable(self):
        now = datetime.now(timezone.utc)
        event = {"home_team": "Home", "away_team": "Away", "bookmakers": [book(core.WINAMAX_KEY, [
            {"key": "alternate_spreads", "last_update": iso(now-timedelta(minutes=2)), "outcomes": [
                {"name": "Home", "point": 1.5, "price": 1.48},
                {"name": "Away", "point": -1.5, "price": 2.75},
            ]}
        ], now-timedelta(minutes=2))]}
        self.assertAlmostEqual(core.winamax_price(event, "RUNLINE", "Home", 1.5), 1.48)
        self.assertAlmostEqual(core.winamax_price(event, "RUNLINE", "Away", -1.5), 2.75)

    def test_stale_winamax_reverse_runline_is_not_executable(self):
        now = datetime.now(timezone.utc)
        stale = now-timedelta(minutes=config.V123_MAX_WINAMAX_AGE_MIN+3)
        event = {"home_team": "Home", "away_team": "Away", "bookmakers": [book(core.WINAMAX_KEY, [
            {"key": "alternate_spreads", "last_update": iso(stale), "outcomes": [
                {"name": "Home", "point": 1.5, "price": 1.48},
                {"name": "Away", "point": -1.5, "price": 2.75},
            ]}
        ], stale)]}
        self.assertIsNone(core.winamax_price(event, "RUNLINE", "Home", 1.5))

    def test_alternate_sharp_devig_uses_only_complementary_pair(self):
        now = datetime.now(timezone.utc)
        event = {"home_team": "Home", "away_team": "Away", "bookmakers": [book("pinnacle", [
            {"key": "alternate_spreads", "last_update": iso(now), "outcomes": [
                {"name": "Home", "point": -1.5, "price": 2.20},
                {"name": "Away", "point": 1.5, "price": 1.70},
                {"name": "Home", "point": 1.5, "price": 1.40},
                {"name": "Away", "point": -1.5, "price": 3.00},
            ]}
        ], now)]}
        consensus = market.sharp_consensus(event, "RUNLINE", "Home", 1.5, as_of=iso(now))
        expected = (1/1.40)/((1/1.40)+(1/3.00))
        self.assertEqual(consensus["n"], 1)
        self.assertAlmostEqual(consensus["p"], expected, places=9)
        self.assertEqual(consensus.get("market_source"), "alternate_spreads")

    def test_analysis_points_expose_both_plus_and_minus_15(self):
        now = datetime.now(timezone.utc)
        outcomes = [
            {"name": "Home", "point": -1.5, "price": 2.15},
            {"name": "Away", "point": 1.5, "price": 1.72},
            {"name": "Home", "point": 1.5, "price": 1.47},
            {"name": "Away", "point": -1.5, "price": 2.80},
        ]
        event = {"home_team": "Home", "away_team": "Away", "bookmakers": [book(core.WINAMAX_KEY, [
            {"key": "alternate_spreads", "last_update": iso(now), "outcomes": outcomes}
        ], now)]}
        points, source = engine._analysis_points(event, "spreads", "Home", iso(now))
        self.assertEqual(points, [-1.5, 1.5])
        self.assertIn(source, {"winamax", "mixed"})

    def test_standard_runline_remains_the_only_canonical_line(self):
        now = datetime.now(timezone.utc)
        event = {"home_team": "Home", "away_team": "Away", "bookmakers": [book(core.WINAMAX_KEY, [
            {"key": "spreads", "last_update": iso(now), "outcomes": [
                {"name": "Home", "point": -1.5, "price": 2.10},
                {"name": "Away", "point": 1.5, "price": 1.75},
            ]},
            {"key": "alternate_spreads", "last_update": iso(now), "outcomes": [
                {"name": "Home", "point": 1.5, "price": 1.45},
                {"name": "Away", "point": -1.5, "price": 2.90},
            ]},
        ], now)]}
        self.assertEqual(engine._canonical_spread_point(event, "Home"), -1.5)
        points, _ = engine._analysis_points(event, "spreads", "Home", iso(now))
        self.assertEqual(points, [-1.5, 1.5])

    def test_odds_enrichment_queries_only_target_date_and_merges_market(self):
        target = "2026-08-14"
        event = {"id": "evt-1", "commence_time": "2026-08-14T18:00:00Z", "home_team": "Home",
                 "away_team": "Away", "bookmakers": []}
        other = {"id": "evt-2", "commence_time": "2026-08-15T18:00:00Z", "home_team": "X",
                 "away_team": "Y", "bookmakers": []}
        extra = {"bookmakers": [{"key": core.WINAMAX_KEY, "last_update": "2026-08-14T17:55:00Z", "markets": [
            {"key": "alternate_spreads", "last_update": "2026-08-14T17:55:00Z", "outcomes": [
                {"name": "Home", "point": 1.5, "price": 1.50},
                {"name": "Away", "point": -1.5, "price": 2.65},
            ]}
        ]}]}
        with patch.dict(alt._ORIGINALS, {"core.odds_api": lambda: [event, other]}, clear=False), \
             patch.object(core, "TARGET_DATE", target), \
             patch.object(core, "http_json", return_value=extra) as mocked:
            enriched = alt.odds_api_with_alternate_runlines()
        self.assertEqual(mocked.call_count, 1)
        alt_market = next(m for m in enriched[0]["bookmakers"][0]["markets"] if m["key"] == "alternate_spreads")
        self.assertEqual(len(alt_market["outcomes"]), 2)
        self.assertFalse(enriched[1].get("alternate_runlines_fetched", False))


if __name__ == "__main__":
    unittest.main()
