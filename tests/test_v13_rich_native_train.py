import unittest

from v11 import v13_rich_native_train as native


class NativeRichTrainTests(unittest.TestCase):
    def row(self,i,point_in_time=True,postgame=False):
        modules={name:{"status":"ACTIVE","coverage":1.0,"home_factor":1.01,"away_factor":.99} for name in native.rich.MODULES}
        return {"game_pk":1000+i,"game_date":f"2026-08-{1+(i//15):02d}T18:00:00Z","analyzed_at":f"2026-08-{1+(i//15):02d}T16:00:00Z",
                "result_status":"FINAL","home_score":5,"away_score":3,"projected_home_runs":4.6,"projected_away_runs":4.1,
                "point_in_time":point_in_time,"features_from_postgame":postgame,"shadow_v124":{"modules":modules}}

    def test_requires_native_volume(self):
        report=native.build([self.row(i) for i in range(50)])
        self.assertEqual(report["status"],"COLLECTING")
        self.assertFalse(report["active_for_production"])
        self.assertEqual(report["native_games"],50)

    def test_postgame_and_non_point_in_time_rows_are_excluded(self):
        rows=[self.row(1),self.row(2,point_in_time=False),self.row(3,postgame=True)]
        selected=native._native_rows(rows)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]["game_pk"],1001)

    def test_latest_snapshot_per_game_only(self):
        a=self.row(1); b=dict(a); b["analyzed_at"]="2026-08-01T17:00:00Z"; b["projected_home_runs"]=4.9
        selected=native._native_rows([a,b])
        self.assertEqual(len(selected),1)
        self.assertAlmostEqual(selected[0]["home_mu"],4.9)


if __name__ == "__main__": unittest.main()
