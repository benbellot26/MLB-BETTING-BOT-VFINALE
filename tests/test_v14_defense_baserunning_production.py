from __future__ import annotations

import unittest

from v14.defense_baserunning_challenger import FRESH_DAYS, build


def artifact(cutoff: str) -> dict:
    return {
        "schema": "pulsar-v14-defense-baserunning-priors-v4",
        "role": "PRODUCTION_ADVANCED_INPUT",
        "point_in_time": True,
        "cutoff_day": cutoff,
        "champion_impact": True,
        "teams": {
            "1": {"fielding_run_value_per_150": 12.0, "catcher_run_value_per_150": 3.0, "baserunning_runs_per_600_pa": 1.0},
            "2": {"fielding_run_value_per_150": -8.0, "catcher_run_value_per_150": -2.0, "baserunning_runs_per_600_pa": -1.0},
        },
    }


class DefenseBaserunningProductionTests(unittest.TestCase):
    def test_fresh_complete_artifact_is_usable(self):
        out = build(home_team_id=1, away_team_id=2, target_date="2026-08-31", artifact=artifact("2026-08-30"))
        self.assertEqual(out["status"], "READY_SHADOW")
        self.assertEqual(out["role"], "PRODUCTION_ADVANCED_COMPONENT")
        self.assertTrue(out["champion_impact"])
        self.assertEqual(out["artifact_freshness"], "FRESH")
        self.assertLess(out["home"]["defense_factor"], 1.0)
        self.assertGreater(out["away"]["defense_factor"], 1.0)
        self.assertFalse(out["market_probability_used_as_feature"])

    def test_stale_artifact_is_neutralized(self):
        stale_day = f"2026-08-{30-FRESH_DAYS:02d}"
        out = build(home_team_id=1, away_team_id=2, target_date="2026-08-31", artifact=artifact(stale_day))
        self.assertEqual(out["status"], "COLLECTING")
        self.assertEqual(out["artifact_freshness"], "STALE")
        self.assertNotIn("home", out)

    def test_future_cutoff_is_rejected(self):
        out = build(home_team_id=1, away_team_id=2, target_date="2026-08-31", artifact=artifact("2026-09-01"))
        self.assertEqual(out["status"], "COLLECTING")
        self.assertEqual(out["artifact_freshness"], "FUTURE_LEAKAGE")

    def test_incomplete_team_never_imputes_missing_component(self):
        payload = artifact("2026-08-30")
        del payload["teams"]["1"]["catcher_run_value_per_150"]
        out = build(home_team_id=1, away_team_id=2, target_date="2026-08-31", artifact=payload)
        self.assertEqual(out["status"], "COLLECTING")
        self.assertEqual(out["home"]["status"], "COLLECTING")
        self.assertIn("catcher", out["home"]["missing"])


if __name__ == "__main__":
    unittest.main()
