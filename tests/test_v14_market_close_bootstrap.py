from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.market_close_bootstrap import bootstrap
from v14.market_close_ledger import _read

GAME_DATE = "2026-08-25T23:00:00Z"
NOW = datetime(2026, 8, 25, 22, 0, tzinfo=timezone.utc)


def _prediction(
    *,
    game_pk="123",
    analyzed_at="2026-08-25T20:00:00Z",
    game_date=GAME_DATE,
    event_id="odds-123",
    event_time=GAME_DATE,
    total_line=8.5,
    fresh=True,
    generation=MODEL_GENERATION,
    policy=PROBABILITY_POLICY_ID,
):
    return {
        "schema": "pulsar-v14-prediction-record-v6",
        "model_generation": generation,
        "probability_policy_id": policy,
        "game_pk": game_pk,
        "target_date": "2026-08-25",
        "game_date": game_date,
        "analyzed_at": analyzed_at,
        "home": "Home",
        "away": "Away",
        "total_line": total_line,
        "market_snapshot": {
            "event_id": event_id,
            "commence_time": event_time,
            "freshness_verified": fresh,
        },
    }


def _write_predictions(path: Path, rows):
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class V14MarketCloseBootstrapTests(unittest.TestCase):
    def test_bootstraps_still_future_strict_pregame_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            ledger = Path(tmp) / "close.jsonl"
            _write_predictions(predictions, [_prediction()])
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 1)
            rows = _read(ledger)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_pk"], "123")
            self.assertEqual(rows[0]["odds_event_id"], "odds-123")
            self.assertEqual(rows[0]["tracked_total_lines"], ["8.5"])
            self.assertEqual(rows[0]["bootstrap_source"], "PERSISTED_PREGAME_PREDICTION")
            self.assertTrue(rows[0]["research_only"])
            self.assertFalse(rows[0]["certification_eligible"])
            self.assertFalse(rows[0]["champion_impact"])

    def test_never_bootstraps_after_first_pitch(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            ledger = Path(tmp) / "close.jsonl"
            _write_predictions(predictions, [_prediction()])
            after = datetime(2026, 8, 25, 23, 1, tzinfo=timezone.utc)
            self.assertEqual(bootstrap(predictions, ledger, now=after), 0)
            self.assertEqual(_read(ledger), [])

    def test_rejects_postgame_analysis_bad_identity_or_stale_snapshot(self):
        cases = [
            _prediction(analyzed_at="2026-08-25T23:01:00Z"),
            _prediction(event_time="2026-08-26T02:00:00Z"),
            _prediction(fresh=False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            ledger = Path(tmp) / "close.jsonl"
            _write_predictions(predictions, cases)
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 0)
            self.assertEqual(_read(ledger), [])

    def test_rejects_wrong_generation_policy_or_schema(self):
        bad_schema = _prediction()
        bad_schema["schema"] = "legacy"
        cases = [
            _prediction(generation="old-generation"),
            _prediction(policy="old-policy"),
            bad_schema,
        ]
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            ledger = Path(tmp) / "close.jsonl"
            _write_predictions(predictions, cases)
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 0)
            self.assertEqual(_read(ledger), [])

    def test_dedupes_game_and_retains_multiple_pregame_total_lines(self):
        rows = [
            _prediction(analyzed_at="2026-08-25T19:00:00Z", total_line=8.5),
            _prediction(analyzed_at="2026-08-25T21:00:00Z", total_line=9.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            ledger = Path(tmp) / "close.jsonl"
            _write_predictions(predictions, rows)
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 1)
            archived = _read(ledger)
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0]["tracked_total_lines"], ["8.5", "9"])
            self.assertEqual(archived[0]["latest_total_line"], 9.0)
            self.assertEqual(archived[0]["latest_tracked_at"], "2026-08-25T21:00:00Z")
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 0)

    def test_conflicting_event_id_cannot_mutate_existing_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            ledger = Path(tmp) / "close.jsonl"
            _write_predictions(predictions, [_prediction()])
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 1)
            _write_predictions(
                predictions,
                [_prediction(analyzed_at="2026-08-25T21:30:00Z", event_id="other", total_line=9.5)],
            )
            self.assertEqual(bootstrap(predictions, ledger, now=NOW), 0)
            row = _read(ledger)[0]
            self.assertEqual(row["odds_event_id"], "odds-123")
            self.assertEqual(row["tracked_total_lines"], ["8.5"])


if __name__ == "__main__":
    unittest.main()
