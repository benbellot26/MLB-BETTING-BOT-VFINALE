import tempfile
from pathlib import Path
import unittest

from v14 import MODEL_GENERATION
from v14.tracking import append_snapshot, performance_report, settle_predictions, _read_jsonl


def payload():
    return {
        "model_generation": MODEL_GENERATION,
        "target_date": "2026-08-25",
        "results": [{
            "game_pk": "123",
            "game_date": "2026-08-25T18:00:00Z",
            "analyzed_at": "2026-08-25T12:00:00Z",
            "home": "Home",
            "away": "Away",
            "canonical_lines": {"TOTAL": 8.5},
            "v14_prediction": {
                "model_generation": MODEL_GENERATION,
                "run_projection": {"home_mu": 4.8, "away_mu": 3.9, "total_line": 8.5},
                "probabilities": {
                    "home_ml": .61, "away_ml": .39,
                    "home_minus_1_5": .42, "away_plus_1_5": .58,
                    "away_minus_1_5": .24, "home_plus_1_5": .76,
                    "over": .54, "under": .46,
                },
            },
        }],
    }


class V14TrackingTests(unittest.TestCase):
    def test_snapshot_is_idempotent_and_settles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predictions.jsonl"
            self.assertEqual(append_snapshot(payload(), path), 1)
            self.assertEqual(append_snapshot(payload(), path), 0)

            def loader(day):
                self.assertEqual(day, "2026-08-25")
                return [{
                    "gamePk": 123,
                    "status": {"abstractGameState": "Final"},
                    "teams": {"home": {"score": 6}, "away": {"score": 3}},
                }]

            self.assertEqual(settle_predictions(path, schedule_loader=loader), 1)
            rows = _read_jsonl(path)
            self.assertTrue(rows[0]["settled"])
            self.assertEqual(rows[0]["home_score"], 6)
            self.assertEqual(rows[0]["away_score"], 3)
            report = performance_report(rows)
            self.assertEqual(report["games_settled"], 1)
            self.assertEqual(report["markets"]["ML"]["n"], 1)
            self.assertEqual(report["markets"]["RL_HOME_-1.5"]["n"], 1)
            self.assertEqual(report["markets"]["TOTAL_OVER"]["n"], 1)
            self.assertIsNotNone(report["overall"]["brier"])
            self.assertEqual(report["roi"]["status"], "UNAVAILABLE")

    def test_wrong_generation_is_rejected(self):
        bad = payload()
        bad["model_generation"] = "old"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                append_snapshot(bad, Path(tmp) / "predictions.jsonl")


if __name__ == "__main__":
    unittest.main()
