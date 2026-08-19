from __future__ import annotations

import unittest

from v11 import v139_engineering_closure as closure


class V139EngineeringClosureTests(unittest.TestCase):
    def test_registry_is_exactly_ninety_unique_engineering_points(self):
        report = closure.build()
        self.assertEqual(report["total_points"], 90)
        ids = [point["id"] for point in report["points"]]
        self.assertEqual(ids, list(range(1, 91)))
        self.assertEqual(len({point["name"] for point in report["points"]}), 90)
        self.assertIn("derived from the earlier conservative ~90-point estimate", report["scope_note"])

    def test_all_ninety_engineering_acceptance_points_are_closed(self):
        report = closure.build()
        if report["open_points"]:
            details = "\n".join(
                f"#{point['id']} {point['category']}: {point['name']} -> {point['implementation']}"
                for point in report["open_points"]
            )
            self.fail(f"V13.9 engineering acceptance remains open:\n{details}")
        self.assertEqual(report["engineering_closed"], 90)
        self.assertEqual(report["engineering_open"], 0)
        self.assertTrue(report["all_engineering_closed"])

    def test_engineering_registry_does_not_claim_statistical_evidence_closure(self):
        report = closure.build()
        self.assertIn("Statistical evidence gates remain separate", report["scope_note"])
        self.assertIn("does not activate challengers", report["evidence_note"])


if __name__ == "__main__":
    unittest.main()
