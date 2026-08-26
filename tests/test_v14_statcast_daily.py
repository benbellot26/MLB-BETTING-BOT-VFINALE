from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from v14.statcast_daily import refresh


def artifact(*,split_players:int=2,split_buckets:int=5,source_end:str="2026-08-25",schema:str="pulsar-v14-statcast-id-priors-v2"):
    return {
        "schema":"pulsar-v14-statcast-pit-backfill-v2","point_in_time":True,"stable_id_only":True,"champion_impact":False,
        "source_start":"2026-07-12","source_end":source_end,"raw_pitch_rows":123,"raw_rows_sha256":"abc","requests":[{}],
        "coverage":{"hitters":10,"pitchers":8,"hitter_pitch_split_players":split_players,"hitter_pitch_split_buckets":split_buckets},
        "priors":{"schema":schema,"point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-08-26","hitters":{"1":{"pitch_type_splits":{"FF":{"pa":20}}}},"pitchers":{"2":{"pitch_mix":{"FF":1.0}}},"diagnostics":{"hitter_pitch_split_players":split_players,"hitter_pitch_split_buckets":split_buckets}},
    }


class StatcastDailyTests(unittest.TestCase):
    def test_refresh_writes_shadow_only_enriched_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            priors=Path(td)/"p.json.gz"; report=Path(td)/"r.json"
            out=refresh("2026-08-26",lookback_days=45,priors_path=priors,report_path=report,builder=lambda cutoff,season_start=None:artifact())
            self.assertTrue(priors.exists()); self.assertTrue(report.exists())
            with gzip.open(priors,"rt",encoding="utf-8") as fh:data=json.load(fh)
            self.assertEqual(data["schema"],"pulsar-v14-statcast-id-priors-v2")
            self.assertFalse(data["champion_impact"]); self.assertFalse(data["auto_activation"])
            self.assertEqual(data["rolling_window_days"],45)
            self.assertEqual(out["role"],"SHADOW_DATA_ONLY"); self.assertFalse(out["champion_impact"]); self.assertFalse(out["auto_activation"])

    def test_refresh_refuses_missing_pitch_split_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p.gz",report_path=Path(td)/"r.json",builder=lambda cutoff,season_start=None:artifact(split_players=0,split_buckets=0))

    def test_refresh_refuses_cutoff_crossing_or_wrong_schema(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p.gz",report_path=Path(td)/"r.json",builder=lambda cutoff,season_start=None:artifact(source_end="2026-08-26"))
            with self.assertRaises(ValueError):
                refresh("2026-08-26",priors_path=Path(td)/"p2.gz",report_path=Path(td)/"r2.json",builder=lambda cutoff,season_start=None:artifact(schema="legacy"))


if __name__=="__main__":unittest.main()
