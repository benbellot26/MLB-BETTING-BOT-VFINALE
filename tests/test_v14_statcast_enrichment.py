from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from v14.pitch_matchup_challenger import build as build_matchup
from v14.statcast_enrichment import aggregate_statcast_priors
from v14.statcast_shadow import build_shadow_features, load_priors


def pitch(day:str,batter:str,pitcher:str,ptype:str,pitch_number:int=1,event:str="single",xwoba:str="0.410",description:str="hit_into_play",p_throws:str="R",stand:str="L"):
    return {"game_date":day,"game_pk":"1","at_bat_number":"1","pitch_number":str(pitch_number),"batter":batter,"pitcher":pitcher,"pitch_type":ptype,"events":event,"description":description,"estimated_woba_using_speedangle":xwoba,"launch_speed":"100","launch_speed_angle":"6","release_speed":"95","p_throws":p_throws,"stand":stand}


class StatcastEnrichmentTests(unittest.TestCase):
    def test_enrichment_keeps_exact_pitch_codes_handedness_and_excludes_cutoff_day(self):
        rows=[pitch("2026-08-24","101","201","FF",1,p_throws="R",stand="L"),pitch("2026-08-24","101","201","SL",2,p_throws="R",stand="L"),pitch("2026-08-25","101","201","CH",3,p_throws="L",stand="R")]
        out=aggregate_statcast_priors(rows,"2026-08-25");self.assertEqual(out["schema"],"pulsar-v14-statcast-id-priors-v2");self.assertTrue(out["point_in_time"]);self.assertTrue(out["stable_id_only"]);splits=out["hitters"]["101"]["pitch_type_splits"];self.assertEqual(set(splits),{"FF","SL"});self.assertNotIn("CH",splits);self.assertEqual(set(out["hitters"]["101"]["pitcher_hand_splits"]),{"R"});self.assertEqual(set(out["pitchers"]["201"]["batter_side_splits"]),{"L"});self.assertEqual(out["pitchers"]["201"]["pitch_hand"],"R");self.assertGreater((out.get("diagnostics") or {}).get("hitter_pitch_split_players",0),0);self.assertGreater((out.get("diagnostics") or {}).get("hitter_pitcher_hand_split_players",0),0);self.assertFalse((out.get("v14_enrichment") or {}).get("head_to_head_used"))

    def test_loader_accepts_enriched_schema(self):
        payload={"schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-08-25","hitters":{},"pitchers":{}}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"p.json.gz"
            with gzip.open(path,"wt",encoding="utf-8") as fh:json.dump(payload,fh)
            self.assertEqual(load_priors(path).get("schema"),payload["schema"])

    def test_pitch_matchup_is_order_weighted_and_reports_hand_split_separately(self):
        hitters={}
        for pid in ["101","102","103","104","105","201","202","203","204","205"]:
            home=pid.startswith("1");hitters[pid]={"pitch_type_splits":{"FF":{"pa":120,"xwoba":.380 if home else .280},"SL":{"pa":120,"xwoba":.300 if home else .340}},"pitcher_hand_splits":{"R":{"pa":160,"xwoba":.370 if home else .290},"L":{"pa":160,"xwoba":.310 if home else .350}}}
        artifact={"schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"hitters":hitters}
        feature={"context":{"home_lineup":{"players":[{"id":int(x)} for x in [101,102,103,104,105]]},"away_lineup":{"players":[{"id":int(x)} for x in [201,202,203,204,205]]}}}
        statcast={"home":{"starter":{"pitch_mix":{"FF":1.0},"pitch_hand":"R"}},"away":{"starter":{"pitch_mix":{"SL":1.0},"pitch_hand":"L"}}}
        out=build_matchup(feature,statcast,artifact);self.assertEqual(out["status"],"READY_SHADOW");self.assertLess(out["home_offense"]["matchup_xwoba"],.320);self.assertLess(out["away_offense"]["matchup_xwoba"],.320);self.assertEqual(set(out["home_offense"]["starter_pitch_mix"]),{"SL"});self.assertEqual(set(out["away_offense"]["starter_pitch_mix"]),{"FF"});self.assertTrue(out["home_offense"]["lineup_order_weighted"]);self.assertEqual(out["home_offense"]["starter_pitch_hand"],"L");self.assertEqual(out["away_offense"]["starter_pitch_hand"],"R");self.assertGreater(out["home_offense"]["handedness_covered_hitters"],0);self.assertIsNotNone(out["home_offense"]["handedness_xwoba"]);self.assertFalse(out["home_offense"]["handedness_combined_into_primary"]);self.assertFalse(out["head_to_head_used"])

    def test_statcast_shadow_exposes_pitcher_hand_without_champion_activation(self):
        hitters={str(x):{"pa":100,"xwoba":.330,"pitch_type_splits":{},"pitcher_hand_splits":{"R":{"pa":80,"xwoba":.340}}} for x in range(1,10)}
        pitchers={"20":{"pa":200,"xwoba":.310,"pitch_mix":{"FF":.6,"SL":.4},"pitch_hand":"R","batter_side_splits":{"L":{"pa":100,"xwoba":.320}}},"21":{"pa":200,"xwoba":.330,"pitch_mix":{"FF":.5,"CH":.5},"pitch_hand":"L","batter_side_splits":{"R":{"pa":100,"xwoba":.340}}}}
        artifact={"schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-08-24","v14_enrichment":{"hitter_pitch_type_splits":True,"hitter_pitcher_hand_splits":True},"hitters":hitters,"pitchers":pitchers};feature={"context":{"home_lineup":{"players":[{"id":i} for i in range(1,6)]},"away_lineup":{"players":[{"id":i} for i in range(5,10)]},"home_starter":{"id":20},"away_starter":{"id":21}},"features":{"bullpen":{"home":{},"away":{}}}}
        shadow=build_shadow_features(feature,target_date="2026-08-25",artifact=artifact);self.assertTrue(shadow["handedness_data_available"]);self.assertEqual(shadow["home"]["starter"]["pitch_hand"],"R");self.assertEqual(shadow["away"]["starter"]["pitch_hand"],"L");self.assertFalse(shadow["auto_activation"])


if __name__=="__main__":unittest.main()
