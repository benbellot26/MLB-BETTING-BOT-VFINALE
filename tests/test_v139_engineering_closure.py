from __future__ import annotations

import unittest

from v11 import v139_engineering_closure as closure


class V139EngineeringClosureTests(unittest.TestCase):
    def test_reconstructed_registry_has_exactly_90_controls(self):
        report = closure.evaluate()
        self.assertEqual(report["total"], 90)
        self.assertFalse(report["historical_original_275_registry_available"])
        self.assertEqual(report["registry_kind"], "reconstructed_from_previous_engineering_estimate")

    def test_all_reconstructed_engineering_controls_are_closed(self):
        report = closure.evaluate()
        open_points = [p for p in report["points"] if not p["engineering_closed"]]
        self.assertEqual(open_points, [], msg=[(p["id"], p["name"], p["checks"]) for p in open_points])
        self.assertEqual(report["engineering_closed"], 90)
        self.assertEqual(report["engineering_open"], 0)


if __name__ == "__main__":
    unittest.main()
