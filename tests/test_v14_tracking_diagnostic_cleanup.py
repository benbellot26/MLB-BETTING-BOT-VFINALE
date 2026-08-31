import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v14.tracking import write_performance


class V14TrackingDiagnosticCleanupTests(unittest.TestCase):
    def test_embedded_certification_can_never_authorize_a_bet(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictions = Path(tmp) / "predictions.jsonl"
            report_path = Path(tmp) / "performance.json"
            predictions.write_text("", encoding="utf-8")

            with (
                patch("v14.tracking.load_pick_performance", return_value={}),
                patch(
                    "v14.certification.evaluate",
                    return_value={
                        "certified": True,
                        "betting_status": "BETTING_CERTIFIED",
                        "reasons": [],
                    },
                ),
                patch("v14.probability_calibration.load_artifact", return_value={}),
            ):
                report = write_performance(predictions, report_path)

            diagnostic = report["betting_certification"]
            self.assertTrue(diagnostic["certified"])
            self.assertEqual(diagnostic["betting_status"], "BETTING_CERTIFIED")
            self.assertEqual(diagnostic["role"], "PERFORMANCE_DIAGNOSTIC_ONLY")
            self.assertFalse(diagnostic["authoritative"])
            self.assertFalse(diagnostic["can_authorize_bet"])
            self.assertIn("v14.certification.load_status()", diagnostic["authoritative_source"])

            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(persisted["betting_certification"]["authoritative"])
            self.assertFalse(persisted["betting_certification"]["can_authorize_bet"])


if __name__ == "__main__":
    unittest.main()
