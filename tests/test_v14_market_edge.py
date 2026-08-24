import unittest

from v14.market_edge import edge_report, make_tracking_record, odds_to_decimal, remove_vig_two_way


class MarketEdgeTests(unittest.TestCase):
    def test_odds_conversion(self):
        self.assertAlmostEqual(odds_to_decimal(+150), 2.5)
        self.assertAlmostEqual(odds_to_decimal(-200), 1.5)
        self.assertAlmostEqual(odds_to_decimal(1.80), 1.80)

    def test_no_vig_symmetric_market(self):
        a, b = remove_vig_two_way(-110, -110)
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(b, 0.5)

    def test_positive_edge_is_diagnostic_only(self):
        report = edge_report(0.58, 1.91, 1.91)
        self.assertGreater(report["edge"], 0)
        self.assertGreater(report["expected_value_per_unit"], 0)
        self.assertFalse(report["market_probability_used_as_feature"])

    def test_tracking_record_contains_audit_fields(self):
        record = make_tracking_record(game_pk=123, market="ML", selection="Home", model_probability=0.58, selection_odds=1.91, opposite_odds=1.91, stake_units=1, closing_odds=1.80)
        for field in ("model_probability", "market_no_vig_probability", "edge_pp", "fair_decimal_odds", "expected_value_per_unit", "model_version", "prediction_timestamp", "stake_units", "closing_odds", "clv_implied_probability_pp"):
            self.assertIn(field, record)
        self.assertFalse(record["market_probability_used_as_feature"])


if __name__ == "__main__":
    unittest.main()
