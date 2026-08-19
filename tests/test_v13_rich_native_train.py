import unittest

from v11 import point_in_time_v13 as pit
from v11 import v13_rich_native_train as native
from v11.probability_contract_v13 import attach_contract


class NativeRichTrainTests(unittest.TestCase):
    def row(self,i,point_in_time=True,postgame=False,phase="FINAL"):
        day=1+(i//15)
        analyzed=f"2026-08-{day:02d}T16:00:00Z"
        modules={name:{"status":"ACTIVE","coverage":1.0,"home_factor":1.01,"away_factor":.99} for name in native.NATIVE_MODULES}
        provenance={name:pit.provenance_entry("test",as_of=analyzed,snapshot=True) for name in ("team_stats","starter_stats","bullpen","weather","lineup")}
        if not point_in_time:
            provenance["lineup"]["observed_at"]=f"2026-08-{day:02d}T17:00:00Z"
        row={"game_pk":1000+i,"game_date":f"2026-08-{day:02d}T18:00:00Z","analyzed_at":analyzed,
             "phase":phase,"result_status":"FINAL","home_score":5,"away_score":3,"hmu":4.6,"amu":4.1,
             "home":"Home","away":"Away","point_in_time":point_in_time,"features_from_postgame":postgame,
             "feature_provenance":provenance,"shadow_v124":{"modules":modules}}
        attach_contract(row)
        return row

    def test_requires_native_volume(self):
        report=native.build([self.row(i) for i in range(50)])
        self.assertEqual(report["status"],"COLLECTING")
        self.assertFalse(report["active_for_production"])
        self.assertEqual(report["native_games"],50)
        self.assertIn("weather_park",report["available_native_modules"])
        self.assertTrue(report["safety"]["point_in_time_validated_from_feature_provenance"])

    def test_postgame_non_point_in_time_and_non_final_phase_are_excluded(self):
        rows=[self.row(1),self.row(2,point_in_time=False),self.row(3,postgame=True),self.row(4,phase="LATE")]
        selected=native._native_rows(rows)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]["game_pk"],1001)

    def test_latest_final_snapshot_per_game_only(self):
        a=self.row(1); b=dict(a); b["analyzed_at"]="2026-08-01T17:00:00Z"; b["hmu"]=4.9
        b["feature_provenance"]={name:pit.provenance_entry("test",as_of=b["analyzed_at"],snapshot=True) for name in ("team_stats","starter_stats","bullpen","weather","lineup")}
        selected=native._native_rows([a,b])
        self.assertEqual(len(selected),1)
        self.assertAlmostEqual(selected[0]["home_mu"],4.9)
        self.assertEqual(selected[0]["mean_source"],"v13_hmu_amu")

    def test_non_contract_row_is_excluded(self):
        row=self.row(8); row.pop("predictive_contract",None)
        self.assertEqual(native._native_rows([row]),[])

    def test_rejection_diagnostics_explain_point_in_time_failure(self):
        rows=[self.row(1),self.row(2,point_in_time=False)]
        selected,reasons=native._native_rows_with_diagnostics(rows)
        self.assertEqual(len(selected),1)
        self.assertTrue(any(k.startswith("pit:feature_observed_after_as_of:lineup") for k in reasons))


if __name__ == "__main__": unittest.main()
