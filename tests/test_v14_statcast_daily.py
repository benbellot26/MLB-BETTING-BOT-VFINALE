from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from v14.statcast_daily import refresh


def artifact(*,split_players:int=2,split_buckets:int=5,hand_hitters:int=2,hand_pitchers:int=2,source_end:str="2026-08-25",schema:str="pulsar-v14-statcast-id-priors-v2"):
    return {
        "schema":"pulsar-v14-statcast-pit-backfill-v3","point_in_time":True,"stable_id_only":True,"champion_impact":False,
        "source_start":"2026-07-12","source_end":source_end,"raw_pitch_rows":123,"raw_rows_sha256":"abc","requests":[{}],
        "coverage":{"hitters":10,"pitchers":8,"hitter_pitch_split_players":split_players,"hitter_pitch_split_buckets":split_buckets,"hitter_pitcher_hand_split_players":hand_hitters,"pitcher_batter_side_split_players":hand_pitchers},
        "priors":{"schema":schema,"point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-08-26","hitters":{"1":{"pitch_type_splits":{"FF":{"pa":20}},"pitcher_hand_splits":{"R":{"pa":20,"xwoba":.330}}}},"pitchers":{"2":{"pitch_mix":{"FF":1.0},"pitch_hand":"R","batter_side_splits":{"L":{"pa":20,"xwoba":.315}}}},"diagnostics":{"hitter_pitch_split_players":split_players,"hitter_pitch_split_buckets":split_buckets,"hitter_pitcher_hand_split_players":hand_hitters,"pitcher_batter_side_split_players":hand_pitchers}},
    }


class StatcastDailyTests(unittest.TestCase):
    def test_refresh_writes_generation_bound_production_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            priors=Path(td)/"p.json.gz"; report=Path(td)/"r.json"
            out=refresh("2026-08-26",lookback_days=45,priors_path=priors,report_path=report,builder=lambda cutoff,season_start=None:artifact())
            self.assertTrue(priors.exists()); self.assertTrue(report.exists())
            with gzip.open(priors,"rt",encoding="utf-8") as fh:data=json.load(fh)
            self.assertEqual(data["schema"],"pulsar-v14-statcast-id-priors-v2")
            self.assertEqual(data["role"],"PRODUCTION_ADVANCED_INPUT")
            self.assertTrue(data["champion_impact"]); self.assertFalse(data["auto_activation"])
            self.assertIn("pulsar-v14-context-v4-all-stats",data["activation_contract"])
            self.assertEqual(data["rolling_window_days"],45)
            self.assertEqual(out["schema"],"pulsar-v14-statcast-daily-report-v3")
            self.assertEqual(out["role"],"PRODUCTION_ADVANCED_INPUT"); self.assertTrue(out["champion_impact"]); self.assertFalse(out["auto_activation"])
            self.assertTrue(out["handedness_enrichment"]); self.assertTrue(out["v14_native_provider"])

    def test_refresh_refuses_missing_pitch_split_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p.gz",report_path=Path(td)/"r.json",builder=lambda cutoff,season_start=None:artifact(split_players=0,split_buckets=0))

    def test_refresh_refuses_missing_handedness_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p.gz",report_path=Path(td)/"r.json",builder=lambda cutoff,season_start=None:artifact(hand_hitters=0,hand_pitchers=0))

    def test_refresh_refuses_cutoff_crossing_or_wrong_schema(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p.gz",report_path=Path(td)/"r.json",builder=lambda cutoff,season_start=None:artifact(source_end="2026-08-26"))
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p2.gz",report_path=Path(td)/"r2.json",builder=lambda cutoff,season_start=None:artifact(schema="legacy"))


if __name__=="__main__":unittest.main()
