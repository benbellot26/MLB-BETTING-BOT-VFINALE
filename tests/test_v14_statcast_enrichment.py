from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from v14.pitch_matchup_challenger import build as build_matchup
from v14.statcast_enrichment import aggregate_statcast_priors
from v14.statcast_shadow import load_priors


def pitch(day:str,batter:str,pitcher:str,ptype:str,pitch_number:int=1,event:str="single",xwoba:str="0.410",description:str="hit_into_play"):
    return {"game_date":day,"game_pk":"1","at_bat_number":"1","pitch_number":str(pitch_number),"batter":batter,"pitcher":pitcher,"pitch_type":ptype,"events":event,"description":description,"estimated_woba_using_speedangle":xwoba,"launch_speed":"100","launch_speed_angle":"6","release_speed":"95"}


class StatcastEnrichmentTests(unittest.TestCase):
    def test_enrichment_keeps_exact_pitch_codes_and_excludes_cutoff_day(self):
        rows=[pitch("2026-08-24","101","201","FF",1),pitch("2026-08-24","101","201","SL",2),pitch("2026-08-25","101","201","CH",3)]
        out=aggregate_statcast_priors(rows,"2026-08-25")
        self.assertEqual(out["schema"],"pulsar-v14-statcast-id-priors-v2")
        self.assertTrue(out["point_in_time"]); self.assertTrue(out["stable_id_only"])
        splits=out["hitters"]["101"]["pitch_type_splits"]
        self.assertEqual(set(splits),{"FF","SL"})
        self.assertNotIn("CH",splits)
        self.assertGreater((out.get("diagnostics") or {}).get("hitter_pitch_split_players",0),0)
        self.assertFalse((out.get("v14_enrichment") or {}).get("head_to_head_used"))

    def test_loader_accepts_enriched_schema(self):
        payload={"schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-08-25","hitters":{},"pitchers":{}}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"p.json.gz"
            with gzip.open(path,"wt",encoding="utf-8") as fh: json.dump(payload,fh)
            self.assertEqual(load_priors(path).get("schema"),payload["schema"])

    def test_pitch_matchup_uses_opponent_starter_mix_and_hitter_splits(self):
        hitters={}
        for pid in ["101","102","103","104","105","201","202","203","204","205"]:
            home=pid.startswith("1")
            hitters[pid]={"pitch_type_splits":{"FF":{"pa":120,"xwoba":.380 if home else .280},"SL":{"pa":120,"xwoba":.300 if home else .340}}}
        artifact={"schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"hitters":hitters}
        feature={"context":{"home_lineup":{"players":[{"id":int(x)} for x in [101,102,103,104,105]]},"away_lineup":{"players":[{"id":int(x)} for x in [201,202,203,204,205]]}}}
        statcast={"home":{"starter":{"pitch_mix":{"FF":1.0}}},"away":{"starter":{"pitch_mix":{"SL":1.0}}}}
        out=build_matchup(feature,statcast,artifact)
        self.assertEqual(out["status"],"READY_SHADOW")
        # Home hitters face the away SL-only starter; away hitters face home FF.
        self.assertLess(out["home_offense"]["matchup_xwoba"],.320)
        self.assertLess(out["away_offense"]["matchup_xwoba"],.320)
        self.assertEqual(set(out["home_offense"]["starter_pitch_mix"]),{"SL"})
        self.assertEqual(set(out["away_offense"]["starter_pitch_mix"]),{"FF"})
        self.assertFalse(out["head_to_head_used"])


if __name__=="__main__":unittest.main()
