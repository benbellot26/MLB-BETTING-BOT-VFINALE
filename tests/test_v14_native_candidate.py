import unittest

from v14 import MODEL_GENERATION
from v14.acquisition import PregameSnapshot
from v14.mlb_inputs import NativeGameInputs
from v14.native_candidate import build_candidate, compare_with_legacy
from v14.run_stack import StructuralRunInput


def _game():
    return {"gamePk":123,"gameDate":"2026-08-25T23:00:00Z","venue":{"name":"Test Park"},"teams":{"home":{"team":{"id":1,"name":"Home"}},"away":{"team":{"id":2,"name":"Away"}}}}

def _event():
    return {"id":"evt","home_team":"Home","away_team":"Away","bookmakers":[{"key":"pinnacle","markets":[{"key":"totals","outcomes":[{"name":"Over","point":8.5,"price":1.91},{"name":"Under","point":8.5,"price":1.91}]}]}]}

def _collector(target_date,analyzed_at=None,api_key=None):
    game=_game(); return PregameSnapshot(target_date=target_date,analyzed_at=analyzed_at,games=[game],events=[_event()],matches={"123":_event()})

def _builder(game,target_date,analyzed_at):
    feature={"game_pk":"123","as_of":analyzed_at,"point_in_time":True,"point_in_time_validation_reasons":[],"data_quality":{"eligible":True,"starter_complete":False,"home_lineup_count":0,"away_lineup_count":0},"context":{"home_lineup":{"count":0},"away_lineup":{"count":0}},"features":{},"rich_modules":{}}
    return NativeGameInputs(structural=StructuralRunInput(game_pk="123",game_date="2026-08-25T23:00:00Z",venue="Test Park",structural_home_mu=4.5,structural_away_mu=4.2,static_park_factor=1.0),home="Home",away="Away",context={"home":"Home","away":"Away","home_lineup":{"count":0},"away_lineup":{"count":0}},feature_row=feature,structural_debug={"source":"test"})

class V14NativeCandidateTests(unittest.TestCase):
    def test_candidate_is_native_non_publishing(self):
        candidate=build_candidate("2026-08-25",analyzed_at="2026-08-25T18:00:00Z",api_key="secret",collector=_collector,input_builder=_builder)
        self.assertEqual(candidate["role"],"CANDIDATE_NON_PUBLISHING"); self.assertEqual(candidate["coverage"]["priced_games"],1); result=candidate["results"][0]; self.assertEqual(result["phase"],"EARLY"); self.assertEqual(result["v14_prediction"]["phase"],"EARLY"); self.assertEqual(result["canonical_lines"]["TOTAL"],8.5); self.assertEqual(result["v14_prediction"]["model_generation"],MODEL_GENERATION)
    def test_late_snapshot_without_announced_starters_is_skipped(self):
        candidate=build_candidate("2026-08-25",analyzed_at="2026-08-25T20:30:00Z",collector=_collector,input_builder=_builder)
        self.assertEqual(candidate["coverage"]["priced_games"],0); self.assertIn("requires both announced starting pitchers",candidate["skipped"][0]["reason"])
    def test_parity_report_never_authorizes_cutover_by_itself(self):
        candidate=build_candidate("2026-08-25",analyzed_at="2026-08-25T18:00:00Z",collector=_collector,input_builder=_builder); legacy={"results":[{"game_pk":"123","features":{"structural_home_mu":4.4,"structural_away_mu":4.3}}]}; report=compare_with_legacy(candidate,legacy); self.assertEqual(report["comparable_games"],1); self.assertAlmostEqual(report["max_abs_structural_run_delta"],.1,places=12); self.assertFalse(report["cutover_authorized"])

if __name__=="__main__": unittest.main()
