from __future__ import annotations

import unittest

from v14.statcast_shadow import build_shadow_features


class V14BullpenQualityAvailabilityTests(unittest.TestCase):
    def test_available_reliever_quality_is_weighted_by_recent_workload(self)->None:
        artifact={
            "schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-09-01","hitters":{},
            "pitchers":{
                "1":{"pa":240,"xwoba":.280,"hard_hit_rate":.33,"barrel_rate":.05,"k_minus_bb_rate":.22,"avg_release_speed":96.0},
                "2":{"pa":240,"xwoba":.330,"hard_hit_rate":.39,"barrel_rate":.09,"k_minus_bb_rate":.13,"avg_release_speed":94.0},
                "3":{"pa":240,"xwoba":.350,"hard_hit_rate":.42,"barrel_rate":.11,"k_minus_bb_rate":.09,"avg_release_speed":92.0},
                "4":{"pa":240,"xwoba":.450,"hard_hit_rate":.55,"barrel_rate":.20,"k_minus_bb_rate":.02,"avg_release_speed":90.0},
            },"v14_enrichment":{}
        }
        row={"point_in_time":True,"context":{"home_lineup":{"players":[]},"away_lineup":{"players":[]},"home_starter":{},"away_starter":{}},"features":{"bullpen":{"home":{"relievers":[
            {"id":1,"pitches_last_3d":0,"available":True},
            {"id":2,"pitches_last_3d":30,"available":True},
            {"id":3,"pitches_last_3d":50,"available":True},
            {"id":4,"pitches_last_3d":0,"available":False,"likely_unavailable":True},
        ]},"away":{"relievers":[]}}}}
        out=build_shadow_features(row,target_date="2026-09-01",artifact=artifact)["home"]["bullpen"]
        self.assertEqual(out["status"],"READY")
        weights={str(x["id"]):x["weight"] for x in out["relievers"]}
        self.assertNotIn("4",weights)
        self.assertGreater(weights["1"],weights["2"])
        self.assertGreater(weights["2"],weights["3"])
        self.assertLess(out["xwoba_allowed"],.350)


if __name__=="__main__":unittest.main()
