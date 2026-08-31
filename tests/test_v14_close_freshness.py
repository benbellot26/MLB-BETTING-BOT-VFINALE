from datetime import datetime, timedelta, timezone
import unittest

from v14 import MODEL_GENERATION, PROBABILITY_POLICY_ID
from v14.certification import MAX_PAPER_CLOSE_AGE_HOURS, _paper_close_freshness_failures
from v14.paper_ledger import report


NOW = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)


def _paper_row() -> dict:
    analyzed = NOW - timedelta(hours=2)
    game = analyzed + timedelta(minutes=30)
    primary = NOW - timedelta(hours=1)
    execution = NOW - timedelta(hours=2)
    return {
        "schema": "pulsar-v14-paper-bet-v8",
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "run_trigger": "SCHEDULED_FINAL",
        "game_pk": "freshness-game",
        "odds_event_id": "event-freshness",
        "odds_event_time_verified": True,
        "target_date": game.date().isoformat(),
        "game_date": game.isoformat(),
        "analyzed_at": analyzed.isoformat(),
        "phase": "FINAL",
        "market": "ML",
        "canonical_market": "ML",
        "selection": "home_ml",
        "execution_odds": 2.0,
        "execution_book": "pinnacle",
        "entry_execution_implied_probability": 0.5,
        "entry_sharp_probability": 0.51,
        "close_quality": "CERTIFIED_CLOSE",
        "close_captured_at": primary.isoformat(),
        "primary_close_quality": "CERTIFIED_CLOSE",
        "primary_close_captured_at": primary.isoformat(),
        "primary_close_minutes_to_game": 10.0,
        "closing_pinnacle_probability": 0.55,
        "certification_clv_pp": 5.0,
        "certification_clv_benchmark": "PINNACLE_NO_VIG",
        "execution_close_quality": "CERTIFIED_CLOSE",
        "execution_close_captured_at": execution.isoformat(),
        "execution_close_minutes_to_game": 12.0,
        "execution_close_odds": 1.90,
        "execution_price_clv_pp": (1 / 1.90 - 0.5) * 100,
        "result": None,
    }


class V14CloseFreshnessTests(unittest.TestCase):
    def test_paper_report_exposes_primary_and_execution_freshness_independently(self):
        out = report([_paper_row()])
        scope = out["by_market"]["ML"]
        self.assertEqual(scope["latest_primary_close_at"], (NOW - timedelta(hours=1)).isoformat())
        self.assertEqual(scope["latest_execution_close_at"], (NOW - timedelta(hours=2)).isoformat())
        self.assertEqual(scope["latest_certified_close_at"], scope["latest_primary_close_at"])
        self.assertEqual(scope["certification_clv"]["n"], 1)
        self.assertEqual(scope["execution_clv"]["n"], 1)

    def test_fresh_primary_cannot_mask_missing_execution_close(self):
        scope = {
            "latest_primary_close_at": (NOW - timedelta(hours=1)).isoformat(),
            "latest_certified_close_at": (NOW - timedelta(hours=1)).isoformat(),
            "latest_execution_close_at": None,
        }
        failures = _paper_close_freshness_failures(scope, "ML", NOW)
        self.assertNotIn("ML_latest_primary_close_missing_or_invalid", failures)
        self.assertIn("ML_latest_execution_close_missing_or_invalid", failures)

    def test_fresh_primary_cannot_mask_stale_execution_close(self):
        scope = {
            "latest_primary_close_at": (NOW - timedelta(hours=1)).isoformat(),
            "latest_execution_close_at": (NOW - timedelta(hours=MAX_PAPER_CLOSE_AGE_HOURS + 1)).isoformat(),
        }
        failures = _paper_close_freshness_failures(scope, "ML", NOW)
        self.assertEqual(failures, [f"ML_latest_execution_close_stale>{MAX_PAPER_CLOSE_AGE_HOURS:.0f}h"])

    def test_primary_legacy_alias_is_accepted_but_execution_requires_own_timestamp(self):
        scope = {
            "latest_certified_close_at": (NOW - timedelta(hours=1)).isoformat(),
            "latest_execution_close_at": (NOW - timedelta(hours=1)).isoformat(),
        }
        self.assertEqual(_paper_close_freshness_failures(scope, "ML", NOW), [])


if __name__ == "__main__":
    unittest.main()
