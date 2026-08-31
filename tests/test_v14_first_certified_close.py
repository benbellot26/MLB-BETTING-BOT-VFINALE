from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v14.cost_aware_close_capture import run


NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _row(game_pk: str, event_id: str | None, *, certified: bool = False) -> dict:
    row = {
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

    def test_row_without_exact_odds_event_id_never_triggers_paid_close_request(self):
        calls = {"events": 0}

        def events_loader():
            calls["events"] += 1
            return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            market = root / "market.jsonl"
            paper = root / "paper.jsonl"
            official = root / "official.jsonl"
            api = root / "api.jsonl"
            _write_jsonl(market, [])
            _write_jsonl(paper, [_row("A", None, certified=False)])
            _write_jsonl(official, [])
            with patch("v14.cost_aware_close_capture.api_allowance", return_value={"allowed": True, "used": 0, "limit": 12}):
                out = run(market, paper, official, api_usage_path=api, events_loader=events_loader, now=NOW)
        self.assertFalse(out["api_call_performed"])
        self.assertEqual(out["due_rows"], 0)
        self.assertEqual(calls["events"], 0)


if __name__ == "__main__":
    unittest.main()
