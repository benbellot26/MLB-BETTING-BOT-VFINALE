from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification_timing import CERTIFICATION_RUN_TRIGGER
from v14.market_close_ledger import (
    ROLE,
    _read,
    capture,
    hydrate_paper,
    record_payload,
    report,
)
from v14.paper_ledger import _read as read_paper
from v14.paper_ledger import record_payload as record_paper

GAME_DATE = "2026-08-25T23:00:00Z"
ANALYZED_AT = "2026-08-25T22:30:00Z"
CLOSE_AT = datetime(2026, 8, 25, 22, 50, tzinfo=timezone.utc)


def _event(event_id="odds-123", commence_time=GAME_DATE):
    return {
        "id": event_id,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": commence_time,
        "bookmakers": [
            {
                "key": "pinnacle",
                "last_update": "2026-08-25T22:49:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home", "price": 1.80},
                            {"name": "Away", "price": 2.10},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Home", "point": -1.5, "price": 2.25},
                            {"name": "Away", "point": 1.5, "price": 1.68},
                            {"name": "Away", "point": -1.5, "price": 3.10},
                            {"name": "Home", "point": 1.5, "price": 1.38},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 8.5, "price": 1.91},
                            {"name": "Under", "point": 8.5, "price": 1.91},
                        ],
                    },
                ],
            }
        ],
    }


def _payload(*, analyzed_at=ANALYZED_AT, event_id="odds-123", event_time=GAME_DATE, edge=True, phase="FINAL", run_trigger=CERTIFICATION_RUN_TRIGGER):
    candidate = {
        "selection": "home_ml",
        "canonical_market": "ML",
        "market": "ML",
        "phase": phase,
        "price": 2.0,
        "execution_book": "pinnacle",
        "execution_source": "LINE_SHOPPED",
        "probability": 0.60,
        "lower_probability": 0.56,
        "model_edge_pp": 10.0,
        "robust_edge_pp": 6.0,
        "sharp_edge_pp": 6.0,
        "robust_sharp_edge_pp": 2.0,
        "primary_sharp_benchmark": "PINNACLE_NO_VIG",
        "pinnacle_probability": 0.54,
        "primary_sharp_edge_pp": 6.0,
        "robust_primary_sharp_edge_pp": 2.0,
        "primary_edge_qualified": edge,
        "betting_edge_qualified": edge,
        "sharp_source_count": 1,
        "sharp_sportsbook_source_count": 1,
        "sharp_exchange_proxy_source_count": 0,
        "edge_qualified": edge,
        "research_ready": edge,
        "market_betting_certified": False,
        "status": "RESEARCH_ONLY",
    }
    return {
        "model_generation": MODEL_GENERATION,
        "run_trigger": run_trigger,
        "target_date": "2026-08-25",
        "analyzed_at": analyzed_at,
        "results": [
            {
                "game_pk": "123",
                "model_generation": MODEL_GENERATION,
                "run_trigger": run_trigger,
                "odds_event_id": event_id,
                "game_date": GAME_DATE,
                "analyzed_at": analyzed_at,
                "phase": phase,
                "home": "Home",
                "away": "Away",
                "canonical_lines": {"TOTAL": 8.5},
                "starter_fallback": {"degraded": False},
                "market_snapshot": {
                    "event_id": event_id,
                    "freshness_verified": True,
                    "commence_time": event_time,
                    "markets": {"ML": {"bookmaker": "pinnacle"}},
                },
                "execution_market": {
                    "freshness_verified": True,
                    "selections": {"home_ml": {"price": 2.0, "bookmaker": "pinnacle"}},
                },
                "sharp_market": {
                    "freshness_verified": True,
                    "selections": {
                        "home_ml": {
                            "fair_probability": 0.54,
                            "source_count": 1,
                            "sportsbook_source_count": 1,
                            "exchange_proxy_source_count": 0,
                            "contributors": [
                                {
                                    "bookmaker": "pinnacle",
                                    "source_type": "SPORTSBOOK",
                                    "fair_probability": 0.54,
                                }
                            ],
                        }
                    },
                },
                "v14_prediction": {
                    "model_generation": MODEL_GENERATION,
                    "run_trigger": run_trigger,
                    "probability_policy_id": PROBABILITY_POLICY_ID,
                    "phase": phase,
                    "calibration": {"probability_policy_id": PROBABILITY_POLICY_ID},
                    "probabilities": {"home_ml": 0.60},
                    "raw_probabilities": {"home_ml": 0.61},
                },
                "decision": {"candidates": [candidate]},
            }
        ],
    }


class V14MarketCloseLedgerTests(unittest.TestCase):
    def test_records_all_tracked_games_even_without_paper_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            paper = Path(tmp) / "paper.jsonl"
            payload = _payload(edge=False)
            self.assertEqual(record_paper(payload, paper), 0)
            self.assertEqual(record_payload(payload, archive), 1)
            rows = _read(archive)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ledger_role"], ROLE)
            self.assertTrue(rows[0]["research_only"])
            self.assertFalse(rows[0]["certification_eligible"])
            self.assertFalse(rows[0]["champion_impact"])
            self.assertEqual(rows[0]["tracked_total_lines"], ["8.5"])

    def test_archive_can_track_early_while_paper_rejects_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            paper = Path(tmp) / "paper.jsonl"
            payload = _payload(phase="EARLY")
            self.assertEqual(record_paper(payload, paper), 0)
            self.assertEqual(record_payload(payload, archive), 1)
            self.assertEqual(len(_read(archive)), 1)
            self.assertEqual(read_paper(paper), [])

    def test_tracks_later_pregame_total_line_without_creating_duplicate_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            self.assertEqual(record_payload(_payload(analyzed_at="2026-08-25T19:00:00Z"), archive), 1)
            later = _payload(analyzed_at="2026-08-25T20:30:00Z")
            later["results"][0]["canonical_lines"]["TOTAL"] = 9.0
            self.assertEqual(record_payload(later, archive), 0)
            row = _read(archive)[0]
            self.assertEqual(row["tracked_total_lines"], ["8.5", "9"])
            self.assertEqual(row["latest_total_line"], 9.0)
            self.assertEqual(row["latest_tracked_at"], "2026-08-25T20:30:00Z")

    def test_rejects_postgame_or_unverified_event_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            self.assertEqual(record_payload(_payload(analyzed_at="2026-08-25T23:01:00Z"), archive), 0)
            self.assertEqual(record_payload(_payload(event_time="2026-08-26T02:00:00Z"), archive), 0)
            self.assertEqual(_read(archive), [])

    def test_capture_requires_exact_event_and_persists_certified_multimarket_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            self.assertEqual(record_payload(_payload(), archive), 1)
            self.assertEqual(capture(archive, events_loader=lambda: [_event("wrong-id")], now=CLOSE_AT), 0)
            self.assertEqual(capture(archive, events_loader=lambda: [_event()], now=CLOSE_AT), 1)
            row = _read(archive)[0]
            close = row["best_close"]
            self.assertEqual(close["quality"], "CERTIFIED_CLOSE")
            self.assertAlmostEqual(close["minutes_to_game"], 10.0)
            self.assertIn("home_ml", close["selections"])
            self.assertIn("home_minus_1_5", close["selections"])
            self.assertIn("away_minus_1_5", close["selections"])
            self.assertIn("8.5", close["totals"])
            self.assertIn("over", close["totals"]["8.5"])
            self.assertEqual(close["execution_prices"]["pinnacle"]["home_ml"], 1.80)
            self.assertIsNotNone(close["selections"]["home_ml"]["pinnacle_no_vig_probability"])
            summary = report(_read(archive))
            self.assertEqual(summary["games_with_certified_close"], 1)
            self.assertFalse(summary["certification_eligible"])
            self.assertEqual(summary["certified_market_coverage"]["ML"], 1)
            self.assertEqual(summary["pinnacle_primary_market_coverage"]["ML"], 1)
            self.assertEqual(summary["certified_market_coverage"]["TOTAL_OVER"], 1)

    def test_archive_close_hydrates_existing_paper_bet_but_never_creates_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            paper = Path(tmp) / "paper.jsonl"
            payload = _payload(edge=True)
            self.assertEqual(record_payload(payload, archive), 1)
            self.assertEqual(capture(archive, events_loader=lambda: [_event()], now=CLOSE_AT), 1)

            # No paper entry exists yet: archive evidence cannot create a bet.
            self.assertEqual(hydrate_paper(archive, paper), 0)
            self.assertEqual(read_paper(paper), [])

            self.assertEqual(record_paper(payload, paper), 1)
            self.assertEqual(hydrate_paper(archive, paper), 1)
            row = read_paper(paper)[0]
            self.assertEqual(row["phase"], "FINAL")
            self.assertEqual(row["run_trigger"], CERTIFICATION_RUN_TRIGGER)
            self.assertEqual(row["close_quality"], "CERTIFIED_CLOSE")
            self.assertEqual(row["close_captured_at"], CLOSE_AT.isoformat())
            self.assertIsNotNone(row["closing_sharp_probability"])
            self.assertIsNotNone(row["closing_pinnacle_probability"])
            self.assertIsNotNone(row["certification_clv_pp"])
            self.assertEqual(row["certification_clv_benchmark"], "PINNACLE_NO_VIG")
            self.assertEqual(row["execution_close_odds"], 1.80)
            self.assertIsNotNone(row["execution_price_clv_pp"])
            self.assertEqual(row["close_history"][-1]["source"], ROLE)

    def test_archive_hydration_rejects_event_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "close.jsonl"
            paper = Path(tmp) / "paper.jsonl"
            payload = _payload(edge=True)
            self.assertEqual(record_payload(payload, archive), 1)
            self.assertEqual(capture(archive, events_loader=lambda: [_event()], now=CLOSE_AT), 1)
            self.assertEqual(record_paper(payload, paper), 1)
            rows = _read(archive)
            rows[0]["odds_event_id"] = "other"
            from v14.market_close_ledger import _write
            _write(rows, archive)
            self.assertEqual(hydrate_paper(archive, paper), 0)
            self.assertIsNone(read_paper(paper)[0]["closing_sharp_probability"])


if __name__ == "__main__":
    unittest.main()
