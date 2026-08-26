from __future__ import annotations

import unittest
from unittest.mock import patch

from v14.historical_distribution_validation import build


def feature(gid:int,season:int):
    day=(gid%20)+1
    def team(rf,ra):
        return {"season_to_date":{"games":50,"runs_for_pg":rf,"runs_against_pg":ra},"last_14_games":{"games":14,"runs_for_pg":rf,"runs_against_pg":ra},"last_7_games":{"games":7,"runs_for_pg":rf,"runs_against_pg":ra}}
    return {
        "game_pk":str(gid),"game_date":f"{season}-06-{day:02d}T20:00:00+00:00","as_of":f"{season}-06-{day:02d}T18:00:00+00:00",
        "features":{"home_team_form":team(4.8,4.2),"away_team_form":team(4.3,4.7),"park_prior":{}}
    }


def label(gid:int,season:int):
    return {"game_pk":str(gid),"home_score":5 if gid%2 else 3,"away_score":3 if gid%2 else 4}


class HistoricalDistributionIsolationTests(unittest.TestCase):
    def test_primary_distribution_validation_never_calls_rejected_run_challenger(self):
        split={
            "tuning":[(feature(i,2024),label(i,2024)) for i in range(1,5)],
            "validation":[(feature(100+i,2025),label(100+i,2025)) for i in range(1,5)],
            "frozen_test":[(feature(200+i,2026),label(200+i,2026)) for i in range(1,5)],
        }
        with patch("v14.historical_distribution_validation.candidate_runs",side_effect=AssertionError("rejected run challenger used")):
            out=build(split)
        contract=out.get("run_mean_contract") or {}
        self.assertEqual(contract.get("selection_and_primary_validation"),"STRICT_TEAM_HISTORY_BASELINE")
        self.assertFalse(contract.get("current_v14_champion_reconstruction_claimed"))
        policy=out.get("sample_policy") or {}
        self.assertTrue(policy.get("validation_2025_full_holdout"))
        self.assertTrue(policy.get("frozen_2026_full_holdout"))
        self.assertEqual(policy.get("validation_2025"),4)
        self.assertEqual(policy.get("frozen_2026"),4)

    def test_rejected_run_challenger_is_sensitivity_only_when_explicitly_supplied(self):
        split={
            "tuning":[(feature(i,2024),label(i,2024)) for i in range(1,5)],
            "validation":[(feature(100+i,2025),label(100+i,2025)) for i in range(1,5)],
            "frozen_test":[(feature(200+i,2026),label(200+i,2026)) for i in range(1,5)],
        }
        params={"season_prior_games":15,"recent14_weight":.1,"recent7_weight":0,"offense_weight":.45,"home_advantage_runs":.08,"park_weight":0}
        out=build(split,params)
        sensitivity=out.get("rejected_run_mean_sensitivity") or {}
        self.assertEqual(sensitivity.get("status"),"SENSITIVITY_ONLY")
        self.assertEqual(sensitivity.get("run_mean_source"),"REJECTED_TEAM_RUN_CHALLENGER")
        self.assertFalse(sensitivity.get("can_authorize_promotion"))


if __name__=="__main__": unittest.main()
