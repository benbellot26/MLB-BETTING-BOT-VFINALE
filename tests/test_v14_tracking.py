import tempfile
from pathlib import Path
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.tracking import append_snapshot, performance_report, settle_predictions, _read_jsonl


def payload(analyzed_at="2026-08-25T12:00:00Z"):
    return {
        "model_generation":MODEL_GENERATION,"target_date":"2026-08-25","analyzed_at":analyzed_at,
        "results":[{
            "game_pk":"123","game_date":"2026-08-25T18:00:00Z","analyzed_at":analyzed_at,"phase":"EARLY","home":"Home","away":"Away","canonical_lines":{"TOTAL":8.5},
            "market_snapshot":{"schema":"pulsar-v14-market-snapshot-v2","markets":{"ML":{"selections":{"home":{"price":1.90},"away":{"price":2.00}}},"TOTAL":{"selections":{"over":{"price":1.91},"under":{"price":1.91}}}}},
            "market_diagnostics":{"schema":"pulsar-v14-market-diagnostics-v1","markets":{"ML":{"selections":{"home":{"edge_pp":3.1}}}}},
            "v14_prediction":{"model_generation":MODEL_GENERATION,"calibration":{"probability_policy_id":PROBABILITY_POLICY_ID},"run_projection":{"home_mu":4.8,"away_mu":3.9,"total_line":8.5},"probabilities":{"home_ml":.61,"away_ml":.39,"home_minus_1_5":.42,"away_plus_1_5":.58,"away_minus_1_5":.24,"home_plus_1_5":.76,"over":.54,"under":.46}},
        }],
    }

class V14TrackingTests(unittest.TestCase):
    def test_snapshot_is_idempotent_preserves_market_and_settles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"predictions.jsonl"; self.assertEqual(append_snapshot(payload(),path),1); self.assertEqual(append_snapshot(payload(),path),0)
            rows=_read_jsonl(path); self.assertEqual(rows[0]["market_snapshot"]["markets"]["ML"]["selections"]["home"]["price"],1.90); self.assertEqual(rows[0]["market_diagnostics"]["markets"]["ML"]["selections"]["home"]["edge_pp"],3.1); self.assertEqual(rows[0]["probability_policy_id"],PROBABILITY_POLICY_ID)
            def loader(day):
                self.assertEqual(day,"2026-08-25"); return [{"gamePk":123,"status":{"abstractGameState":"Final"},"teams":{"home":{"score":6},"away":{"score":3}}}]
            self.assertEqual(settle_predictions(path,schedule_loader=loader),1); rows=_read_jsonl(path); self.assertTrue(rows[0]["settled"]); report=performance_report(rows); self.assertEqual(report["games_settled"],1); self.assertEqual(report["markets"]["ML"]["n"],1); self.assertIsNotNone(report["overall"]["brier"]); self.assertEqual(report["roi"]["status"],"UNAVAILABLE"); self.assertEqual(report["clv"]["status"],"UNAVAILABLE"); self.assertIn("market_movement_proxy",report)

    def test_postgame_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"strictly pregame"): append_snapshot(payload("2026-08-25T19:00:00Z"),Path(tmp)/"predictions.jsonl")

    def test_wrong_generation_is_rejected(self):
        bad=payload(); bad["model_generation"]="old"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): append_snapshot(bad,Path(tmp)/"predictions.jsonl")

    def test_missing_probability_policy_is_rejected_not_relabelled(self):
        bad=payload(); bad["results"][0]["v14_prediction"]["calibration"].pop("probability_policy_id")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"policy missing or mismatch"):
                append_snapshot(bad,Path(tmp)/"predictions.jsonl")

    def test_wrong_probability_policy_is_rejected(self):
        bad=payload(); bad["results"][0]["v14_prediction"]["calibration"]["probability_policy_id"]="old-policy"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"policy missing or mismatch"):
                append_snapshot(bad,Path(tmp)/"predictions.jsonl")

if __name__=="__main__": unittest.main()
