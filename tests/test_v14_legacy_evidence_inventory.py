from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from v14 import MODEL_GENERATION
from v14.historical_dataset import refresh_manifest, sha256_file, verify_manifest
from v14.legacy_evidence_inventory import market_tracking_inventory, replay_inventory


def _feature(game_pk:int,season:int)->dict:
    day=f"{season}-06-01"
    return {"game_pk":str(game_pk),"season":season,"official_date":day,"game_date":f"{day}T20:00:00Z","as_of":f"{day}T08:00:00Z","features":{},"feature_provenance":{"mlb_prior_results":{"point_in_time_rule":"strictly earlier officialDate only","same_day_games_excluded":True}},"target_labels_embedded":False,"market_data_embedded":False}

def _label(game_pk:int,season:int)->dict:
    day=f"{season}-06-01"
    return {"game_pk":str(game_pk),"season":season,"game_date":f"{day}T20:00:00Z","home_score":5,"away_score":3}

def _write_gz(path:Path,row:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wt",encoding="utf-8") as fh:fh.write(json.dumps(row)+"\n")

def _manifest(path:Path,base:Path)->None:
    files=[]
    for source in sorted(base.glob("team_features_*.jsonl.gz"))+sorted(base.glob("team_labels_*.jsonl.gz")):
        files.append({"path":str(source).replace("\\","/"),"sha256":sha256_file(source),"bytes":source.stat().st_size})
    path.write_text(json.dumps({"schema":"fixture","dataset_version":"fixture","files":files}),encoding="utf-8")


class HistoricalManifestLifecycleTests(unittest.TestCase):
    def _dataset(self,root:Path)->tuple[Path,Path]:
        base=root/"data"/"v137";manifest=root/"manifest.json"
        _write_gz(base/"team_features_2025.jsonl.gz",_feature(1,2025));_write_gz(base/"team_labels_2025.jsonl.gz",_label(1,2025))
        _write_gz(base/"team_features_2026.jsonl.gz",_feature(2,2026));_write_gz(base/"team_labels_2026.jsonl.gz",_label(2,2026));_manifest(manifest,base)
        return base,manifest

    def test_exact_manifest_is_verified(self):
        with TemporaryDirectory() as tmp:
            base,manifest=self._dataset(Path(tmp));out=verify_manifest(manifest,base)
            self.assertTrue(out["verified"]);self.assertEqual(out["integrity_mode"],"EXACT_MANIFEST")

    def test_latest_season_refresh_is_visible_but_research_acceptable(self):
        with TemporaryDirectory() as tmp:
            base,manifest=self._dataset(Path(tmp));_write_gz(base/"team_features_2026.jsonl.gz",{**_feature(2,2026),"cohort":"refreshed"});out=verify_manifest(manifest,base)
            self.assertFalse(out["verified"]);self.assertTrue(out["accepted"]);self.assertEqual(out["integrity_mode"],"CURRENT_SEASON_REFRESH_PENDING_MANIFEST");self.assertEqual(len(out["current_season_refresh"]),1)

    def test_old_season_hash_mismatch_fails_closed(self):
        with TemporaryDirectory() as tmp:
            base,manifest=self._dataset(Path(tmp));_write_gz(base/"team_features_2025.jsonl.gz",{**_feature(1,2025),"cohort":"tampered"})
            with self.assertRaisesRegex(ValueError,"hash mismatch"):verify_manifest(manifest,base)

    def test_refresh_manifest_rebinds_current_sources_after_full_pit_audit(self):
        with TemporaryDirectory() as tmp:
            base,manifest=self._dataset(Path(tmp));_write_gz(base/"team_features_2026.jsonl.gz",{**_feature(2,2026),"cohort":"refreshed"});before=verify_manifest(manifest,base);self.assertFalse(before["verified"])
            refreshed=refresh_manifest(manifest,base);self.assertTrue(refreshed["refreshed"]);self.assertTrue(refreshed["integrity"]["verified"]);self.assertEqual(refreshed["feature_rows"],2)


class LegacyEvidenceInventoryTests(unittest.TestCase):
    def test_replay_inventory_deduplicates_phases_and_rejects_postgame(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"replay.jsonl";rows=[]
            for phase,at in (("EARLY","2026-08-14T12:00:00Z"),("FINAL","2026-08-14T17:40:00Z")):
                rows.append({"game_pk":824643,"game_date":"2026-08-14T18:20:00Z","analyzed_at":at,"phase":phase,"point_in_time":True,"features_from_postgame":False,"market_probability_used_as_baseball_feature":False,"result_status":"SETTLED","predictive_contract":{"model_generation":"legacy-v13"},"options":[{"market":"ML","p_market":.55},{"market":"TOTAL","p_market":.51}]})
            rows.append({**rows[-1],"game_pk":999,"analyzed_at":"2026-08-14T19:00:00Z"})
            path.write_text("".join(json.dumps(row)+"\n" for row in rows),encoding="utf-8");out=replay_inventory(path)
            self.assertEqual(out["unique_games"],1);self.assertEqual(out["independent_latest_pregame_games"],1);self.assertEqual(out["invalid_rows"],1);self.assertFalse(out["exact_current_v14_replay_eligible"])

    def test_market_tracking_never_grants_certification_credit(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"tracking.jsonl";rows=[{"game_pk":1,"game_date":"2026-08-20T20:00:00Z","observation_at":"2026-08-20T18:00:00Z","market":"ML","phase":"FINAL","settled_result":"WIN","model_generation":"legacy-v13"},{"game_pk":2,"game_date":"2026-08-20T21:00:00Z","observation_at":"2026-08-20T19:00:00Z","market":"TOTAL","phase":"FINAL","settled_result":"LOSS","model_generation":MODEL_GENERATION}];path.write_text("".join(json.dumps(row)+"\n" for row in rows),encoding="utf-8");out=market_tracking_inventory(path)
            self.assertEqual(out["strictly_pregame_unique_games"],2);self.assertEqual(out["current_v14_generation_rows"],1);self.assertEqual(out["certification_credit"],0)


if __name__=="__main__":unittest.main()
