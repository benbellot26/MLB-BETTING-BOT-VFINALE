import unittest

from v11 import data_quality
from v11 import point_in_time_v13 as pit
from v11 import uncertainty_v13
from v11 import v13_probability_diagnostics as diagnostics


class V136EvidenceHardeningTests(unittest.TestCase):
    def test_live_snapshot_materialises_validated_point_in_time_state(self):
        row={"game_date":"2026-08-19T20:00:00Z","analyzed_at":"2026-08-19T18:00:00Z"}
        pit.mark_live_snapshot(row,row["analyzed_at"])
        self.assertTrue(row["point_in_time"])
        self.assertFalse(row["features_from_postgame"])
        self.assertTrue(row["point_in_time_validation"]["valid"])
        self.assertEqual(pit.validate_pregame_row(row),(True,[]))

    def test_point_in_time_is_derived_not_trusted(self):
        row={"game_date":"2026-08-19T20:00:00Z","analyzed_at":"2026-08-19T18:00:00Z"}
        pit.mark_live_snapshot(row,row["analyzed_at"])
        row["point_in_time"]=True
        row["feature_provenance"]["lineup"]["observed_at"]="2026-08-19T19:00:00Z"
        valid,reasons=pit.validate_pregame_row(row)
        self.assertFalse(valid)
        self.assertIn("feature_observed_after_as_of:lineup",reasons)

    def _dq_result(self,weather_available,model_active=False):
        players=[{"ops":.720} for _ in range(9)]
        starter={"current_stats_available":True,"prior_available":True}
        return {"phase":"FINAL","ctx":{"home_sp":"H","away_sp":"A","home_starter":starter,"away_starter":starter,
                "home_lineup":{"count":9,"players":players},"away_lineup":{"count":9,"players":players}},
                "features":{"source_quality":{"home_team_hitting":True,"away_team_hitting":True,"home_team_pitching":True,"away_team_pitching":True,
                "home_lineup_usable_ops":9,"away_lineup_usable_ops":9},"weather":{"available":weather_available},"bullpen":{"coverage":1.0}},
                "model":{"active":model_active}}

    def test_inactive_weather_and_rich_bullpen_do_not_artificially_raise_model_dq(self):
        a=data_quality.assess(self._dq_result(False,False))
        b=data_quality.assess(self._dq_result(True,False))
        self.assertEqual(a["model_input_score"],b["model_input_score"])
        self.assertNotIn("weather",a["model_input_contract"])
        self.assertNotIn("bullpen",a["model_input_contract"])

    def test_learned_active_contract_can_use_weather_and_bullpen(self):
        a=data_quality.assess(self._dq_result(False,True))
        b=data_quality.assess(self._dq_result(True,True))
        self.assertIn("weather",a["model_input_contract"])
        self.assertIn("bullpen",a["model_input_contract"])
        self.assertGreaterEqual(b["model_input_score"],a["model_input_score"])

    def test_reliability_sampling_is_not_counted_twice(self):
        old=uncertainty_v13.empirical_interval(.60,calibration_n=100,phase_n=100,market_n=100,empirical_sigma=.08,
                                               empirical_includes_sampling=False,data_quality=.9)
        new=uncertainty_v13.empirical_interval(.60,calibration_n=100,phase_n=100,market_n=100,empirical_sigma=.08,
                                               empirical_includes_sampling=True,data_quality=.9)
        self.assertLessEqual(new["sigma"],old["sigma"])
        self.assertEqual(new["sampling_sigma_added"],0.0)

    def test_probability_diagnostics_use_one_latest_snapshot_per_game_market(self):
        base={"game_pk":1,"game_date":"2026-08-19T20:00:00Z","market":"ML","pick":"Home","home":"Home","away":"Away",
              "p_model":.60,"p_market":.55,"settled_result":"WIN"}
        early={**base,"phase":"EARLY","observation_at":"2026-08-19T10:00:00Z"}
        late={**base,"phase":"LATE","observation_at":"2026-08-19T17:00:00Z","p_model":.62}
        rows=diagnostics.independent_states([early,late])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["phase"],"LATE")
        report=diagnostics.build([early,late])
        self.assertEqual(report["independent_targets"],1)
        self.assertEqual(report["by_market"]["ML"]["n"],1)


if __name__ == "__main__":
    unittest.main()
