from __future__ import annotations

import unittest

from v11 import historical_migration_v13 as migration


class HistoricalMigrationTests(unittest.TestCase):
    def test_old_version_with_saved_baseball_probability_is_calibration_migratable(self):
        row = {
            "game_pk":1,
            "analyzed_at":"2026-06-01T16:00:00+00:00",
            "game_date":"2026-06-01T20:00:00+00:00",
            "home_score":4,"away_score":2,
            "engine_version":"12.3.2-old",
            "options":[{"p_learned":.61,"result":"WIN"}],
        }
        status,_ = migration.classify(row)
        self.assertEqual(status,"MIGRATABLE_CALIBRATION")

    def test_market_blended_only_legacy_row_is_diagnostic(self):
        row = {
            "game_pk":1,
            "analyzed_at":"2026-06-01T16:00:00+00:00",
            "game_date":"2026-06-01T20:00:00+00:00",
            "home_score":4,"away_score":2,
            "options":[{"p_effective":.61,"p_market":.58,"result":"WIN"}],
        }
        status,_ = migration.classify(row)
        self.assertEqual(status,"DIAGNOSTIC_ONLY")

    def test_postgame_row_is_rejected(self):
        row = {
            "game_pk":1,
            "analyzed_at":"2026-06-02T01:00:00+00:00",
            "game_date":"2026-06-01T20:00:00+00:00",
            "home_score":4,"away_score":2,
            "options":[{"p_learned":.61,"result":"WIN"}],
        }
        status,_ = migration.classify(row)
        self.assertEqual(status,"REJECT")


if __name__ == "__main__":
    unittest.main()
