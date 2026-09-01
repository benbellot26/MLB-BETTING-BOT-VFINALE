from __future__ import annotations

import unittest

from v14.statcast_multiwindow_challenger import build_report, select_entity


def artifact(days:int,pa:int)->dict:
    return {"schema":"pulsar-v14-statcast-id-priors-v2","point_in_time":True,"stable_id_only":True,"cutoff_day":"2026-09-01","hitters":{"1":{"pa":pa,"xwoba":.340,"hard_hit_rate":.40,"barrel_rate":.09,"k_minus_bb_rate":.14}},"pitchers":{}}


class V14StatcastMultiwindowTests(unittest.TestCase):
    def test_shortest_adequate_window_is_selected(self)->None:
        artifacts={14:artifact(14,40),30:artifact(30,85),45:artifact(45,120),60:artifact(60,160)}
        out=select_entity("1",artifacts,kind="hitter")
        self.assertEqual(out["selected_window_days"],30)
        self.assertTrue(out["adequate_sample"])

    def test_report_is_shadow_only(self)->None:
        out=build_report({14:artifact(14,40),30:artifact(30,85)})
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertFalse(out["champion_impact"])
        self.assertFalse(out["auto_activation"])
        self.assertFalse(out["market_probability_used_as_feature"])


if __name__=="__main__":unittest.main()
