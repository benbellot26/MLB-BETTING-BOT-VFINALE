from __future__ import annotations

import unittest

from v14.savant_run_value_pit import baserunning_prior_snapshot, fielding_team_snapshot

CSV="team_name,total_runs,catching_runs,runner_runs_tot\nCubs,12,3,4\n"

class V14SavantRunValuePITTests(unittest.TestCase):
    def test_fielding_snapshot_uses_strict_prior_date(self):
        seen=[]
        out=fielding_team_snapshot("2026-08-25",getter=lambda url:(seen.append(url) or CSV))
        self.assertTrue(out["point_in_time"])
        self.assertTrue(out["same_day_excluded"])
        self.assertEqual(out["effective_cutoff"],"2026-08-24")
        self.assertIn("dateEnd=2026-08-24",seen[0])
        self.assertIn("type=fielding-team",seen[0])

    def test_baserunning_uses_only_completed_prior_season(self):
        seen=[]
        out=baserunning_prior_snapshot(2026,getter=lambda url:(seen.append(url) or CSV))
        self.assertEqual(out["source_season"],2025)
        self.assertFalse(out["current_target_season_results_used"])
        self.assertIn("season_start=2025",seen[0])
        self.assertIn("season_end=2025",seen[0])

if __name__=="__main__": unittest.main()
