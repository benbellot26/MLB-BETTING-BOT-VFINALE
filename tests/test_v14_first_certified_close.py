from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.cost_aware_close_capture import hydrate_first_paper, run


NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _row(game_pk: str, event_id: str | None, *, certified: bool = False) -> dict:
    row = {
        "schema": "pulsar-v14-market-close-v1",
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "certification_eligible": False,
        "game_pk": game_pk,
        "odds_event_id": event_id,
        "odds_event_time_verified": True,
        "game_date": (NOW + timedelta(minutes=10)).isoformat(),
        "close_history": [],
        "close_quality": None,
        "best_close": None,
    }
    if certified:
        close = {
            "captured_at": (NOW - timedelta(minutes=1)).isoformat(),
            "minutes_to_game": 11.0,
            "quality": "CERTIFIED_CLOSE",
            "odds_event_id": event_id,
        }
        row["close_history"] = [close]
        row["close_quality"] = "CERTIFIED_CLOSE"
        row["best_close"] = close
    return row


def _event(event_id: str) -> dict:
    return {"id": event_id, "commence_time": (NOW + timedelta(minutes=10)).isoformat(), "bookmakers": []}


def _primary_close(event_id: str, captured_at: datetime, minutes_to_game: float, *, consensus: float, pinnacle: float | None) -> dict:
    selection = {"fair_probability": consensus, "pinnacle_no_vig_probability": pinnacle, "dispersion_pp": 0.5}
    return {
        "captured_at": captured_at.isoformat(),
        "minutes_to_game": minutes_to_game,
        "quality": "CERTIFIED_CLOSE",
        "odds_event_id": event_id,
        "selections": {"home_ml": selection},
        "execution_prices": {"pinnacle": {"home_ml": 1.90}},
    }


def _paper_row(event_id: str, game_pk: str = "A") -> dict:
    return {
        "schema": "pulsar-v14-paper-bet-v8",
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "game_pk": game_pk,
        "odds_event_id": event_id,
        "analyzed_at": NOW.isoformat(),
        "game_date": (NOW + timedelta(minutes=20)).isoformat(),
        "selection": "home_ml",
        "canonical_market": "ML",
        "execution_book": "pinnacle",
        "execution_odds": 2.0,
        "entry_execution_implied_probability": 0.50,
        "entry_sharp_probability": 0.52,
        "close_history": [],
        "close_quality": None,
        "close_captured_at": None,
        "close_minutes_to_game": None,
    }


class V14FirstCertifiedCloseTests(unittest.TestCase):
    def _run_with_spies(self, market_rows, paper_rows, official_rows, events):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market = root / "market.jsonl"
            paper = root / "paper.jsonl"
            official = root / "official.jsonl"
            api = root / "api.jsonl"
            _write_jsonl(market, market_rows)
            _write_jsonl(paper, paper_rows)
            _write_jsonl(official, official_rows)
            seen = {"market": None, "paper": None, "official": None}

            def fake_market(path, *, api_key=None, events_loader=None, now=None):
                seen["market"] = [str(event.get("id")) for event in events_loader()]
                return len(seen["market"])

            def fake_paper(path, *, api_key=None, events_loader=None, now=None):
                seen["paper"] = [str(event.get("id")) for event in events_loader()]
                return len(seen["paper"])

            def fake_official(*, path, api_key=None, events_loader=None, now=None):
                seen["official"] = [str(event.get("id")) for event in events_loader()]
                return len(seen["official"])

            with patch("v14.cost_aware_close_capture.api_allowance", return_value={"allowed": True, "used": 0, "limit": 12}), \
                 patch("v14.cost_aware_close_capture.record_close_snapshot", return_value={"reserved": True}), \
                 patch("v14.cost_aware_close_capture.capture_market", side_effect=fake_market), \
                 patch("v14.cost_aware_close_capture.capture_paper", side_effect=fake_paper), \
                 patch("v14.cost_aware_close_capture.capture_official", side_effect=fake_official):
                out = run(
                    market,
                    paper,
                    official,
                    api_usage_path=api,
                    events_loader=lambda: list(events),
                    now=NOW,
                )
            return out, seen

    def test_paid_snapshot_is_hidden_from_consumer_with_already_certified_row(self):
        out, seen = self._run_with_spies(
            [_row("A", "event-a", certified=True)],
            [_row("B", "event-b", certified=False)],
            [],
            [_event("event-a"), _event("event-b")],
        )
        self.assertTrue(out["api_call_performed"])
        self.assertEqual(out["due_rows"], 1)
        self.assertEqual(seen["market"], [])
        self.assertEqual(seen["paper"], ["event-b"])
        self.assertEqual(seen["official"], [])
        self.assertEqual(out["consumer_event_counts"], {"market": 0, "paper": 1, "official": 0})

    def test_same_game_due_in_paper_cannot_rewrite_already_certified_market_close(self):
        out, seen = self._run_with_spies(
            [_row("A", "event-a", certified=True)],
            [_row("A", "event-a", certified=False)],
            [],
            [_event("event-a")],
        )
        self.assertEqual(out["due_rows"], 1)
        self.assertEqual(seen["market"], [])
        self.assertEqual(seen["paper"], ["event-a"])
        self.assertEqual(seen["official"], [])

    def test_certified_paper_row_cannot_be_rewritten_by_market_due_snapshot(self):
        out, seen = self._run_with_spies(
            [_row("B", "event-b", certified=False)],
            [_row("A", "event-a", certified=True)],
            [],
            [_event("event-a"), _event("event-b")],
        )
        self.assertEqual(out["due_rows"], 1)
        self.assertEqual(seen["market"], ["event-b"])
        self.assertEqual(seen["paper"], [])
        self.assertEqual(seen["official"], [])

    def test_legacy_due_row_without_event_id_preserves_gate_but_sees_no_events(self):
        out, seen = self._run_with_spies(
            [],
            [_row("A", None, certified=False)],
            [],
            [_event("event-a")],
        )
        self.assertTrue(out["api_call_performed"])
        self.assertEqual(out["due_rows"], 1)
        self.assertEqual(out["legacy_due_without_event_id"], 1)
        self.assertEqual(seen["market"], [])
        self.assertEqual(seen["paper"], [])
        self.assertEqual(seen["official"], [])
        self.assertEqual(out["consumer_event_counts"], {"market": 0, "paper": 0, "official": 0})

    def test_hydration_uses_first_usable_pinnacle_primary_close_not_latest_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); market = root / "market.jsonl"; paper = root / "paper.jsonl"
            archive = _row("A", "event-a")
            archive["game_date"] = (NOW + timedelta(minutes=20)).isoformat()
            archive["close_history"] = [
                _primary_close("event-a", NOW + timedelta(minutes=6), 14.0, consensus=0.55, pinnacle=None),
                _primary_close("event-a", NOW + timedelta(minutes=10), 10.0, consensus=0.57, pinnacle=0.56),
                _primary_close("event-a", NOW + timedelta(minutes=15), 5.0, consensus=0.67, pinnacle=0.66),
            ]
            _write_jsonl(market, [archive]); _write_jsonl(paper, [_paper_row("event-a")])
            self.assertEqual(hydrate_first_paper(market, paper), 1)
            hydrated = json.loads(paper.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(hydrated["close_captured_at"], (NOW + timedelta(minutes=10)).isoformat())
            self.assertAlmostEqual(hydrated["closing_sharp_probability"], 0.57)
            self.assertAlmostEqual(hydrated["closing_pinnacle_probability"], 0.56)
            self.assertAlmostEqual(hydrated["certification_clv_pp"], 6.0)
            self.assertEqual(hydrated["certification_clv_benchmark"], "PINNACLE_NO_VIG")

    def test_hydrated_certified_paper_close_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); market = root / "market.jsonl"; paper = root / "paper.jsonl"
            archive = _row("A", "event-a")
            archive["game_date"] = (NOW + timedelta(minutes=20)).isoformat()
            archive["close_history"] = [
                _primary_close("event-a", NOW + timedelta(minutes=8), 12.0, consensus=0.58, pinnacle=0.57),
                _primary_close("event-a", NOW + timedelta(minutes=15), 5.0, consensus=0.68, pinnacle=0.67),
            ]
            _write_jsonl(market, [archive]); _write_jsonl(paper, [_paper_row("event-a")])
            self.assertEqual(hydrate_first_paper(market, paper), 1)
            first = json.loads(paper.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first["close_captured_at"], (NOW + timedelta(minutes=8)).isoformat())
            archive["close_history"] = [_primary_close("event-a", NOW + timedelta(minutes=15), 5.0, consensus=0.78, pinnacle=0.77)]
            _write_jsonl(market, [archive])
            self.assertEqual(hydrate_first_paper(market, paper), 0)
            second = json.loads(paper.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(second["close_captured_at"], first["close_captured_at"])
            self.assertAlmostEqual(second["closing_pinnacle_probability"], first["closing_pinnacle_probability"])


if __name__ == "__main__":
    unittest.main()
