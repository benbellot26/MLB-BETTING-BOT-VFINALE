import tempfile
from pathlib import Path
import unittest

from v14 import MODEL_GENERATION
from v14.native_payload import authorize_payload, build_native_discord_payload
from v14.tracking import append_snapshot, _read_jsonl


class V14EndToEndTrackingTests(unittest.TestCase):
    def test_market_state_and_prospective_shadows_survive_candidate_payload_tracking(self):
        distribution_shadow={"schema":"pulsar-v14-historical-distribution-shadow-v1","status":"READY_SHADOW","role":"SHADOW_ONLY","auto_activation":False,"champion_impact":False,"evidence_run_id":32990513482,"dataset_content_sha256":"abc","candidate_parameters":{"dispersion":5.5,"environment_sigma":.16},"candidate_probabilities":{"home_ml":.57,"away_ml":.43}}
        team_shadow={"schema":"pulsar-v14-historical-team-run-shadow-v1","status":"READY_SHADOW","role":"SHADOW_ONLY","auto_activation":False,"champion_impact":False,"evidence_run_id":32990513482,"dataset_content_sha256":"abc","candidate_run_projection":{"home_mu":4.8,"away_mu":3.9},"candidate_probabilities":{"home_ml":.59,"away_ml":.41}}
        candidate={
            "role":"CANDIDATE_NON_PUBLISHING","native_acquisition":True,"legacy_acquisition_adapter":False,"market_probability_used_as_feature":False,
            "target_date":"2026-08-25","analyzed_at":"2026-08-25T12:00:00Z","coverage":{"matched_odds_games":1,"priced_games":1},
            "results":[{
                "game_pk":"123","game_date":"2026-08-25T18:00:00Z","analyzed_at":"2026-08-25T12:00:00Z","phase":"EARLY","home":"Home","away":"Away","ctx":{},"canonical_lines":{"TOTAL":8.5},"line_selection":{"line":8.5,"market_price_used_as_feature":False},
                "market_snapshot":{"schema":"pulsar-v14-market-snapshot-v2","markets":{"ML":{"selections":{"home":{"price":1.90},"away":{"price":2.00}}}}},
                "market_diagnostics":{"schema":"pulsar-v14-market-diagnostics-v1","markets":{"ML":{"selections":{"home":{"edge_pp":3.0,"expected_value_per_unit":.04}}}}},
                "training_features":{"schema":"pulsar-v14-training-features-v7","capture_mode":"PROSPECTIVE_LIVE_SNAPSHOT","research_challengers":{"historical_distribution_shadow":distribution_shadow,"historical_team_run_shadow":team_shadow}},
                "v14_prediction":{"role":"PRODUCTION","model_generation":MODEL_GENERATION,"game_pk":"123","game_date":"2026-08-25T18:00:00Z","analyzed_at":"2026-08-25T12:00:00Z","home":"Home","away":"Away","phase":"EARLY","total_line":8.5,"market_probability_used_as_feature":False,"run_projection":{"home_mu":4.6,"away_mu":4.0,"total_line":8.5},"probabilities":{"away_ml":.44,"home_ml":.56,"away_plus_1_5":.61,"home_minus_1_5":.39,"home_plus_1_5":.70,"away_minus_1_5":.30,"over":.52,"under":.48}},
            }],
        }
        production=authorize_payload(build_native_discord_payload(candidate),production_authorized=True)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"predictions.jsonl"; self.assertEqual(append_snapshot(production,path),1); row=_read_jsonl(path)[0]
        self.assertEqual(row["market_snapshot"]["markets"]["ML"]["selections"]["home"]["price"],1.90)
        self.assertEqual(row["market_diagnostics"]["markets"]["ML"]["selections"]["home"]["edge_pp"],3.0)
        self.assertFalse((row["market_snapshot"] or {}).get("market_probability_used_as_feature",False))
        research=(row["training_features"] or {})["research_challengers"]
        self.assertEqual(research["historical_distribution_shadow"]["evidence_run_id"],32990513482)
        self.assertEqual(research["historical_distribution_shadow"]["candidate_parameters"],{"dispersion":5.5,"environment_sigma":.16})
        self.assertEqual(research["historical_team_run_shadow"]["candidate_run_projection"]["home_mu"],4.8)
        self.assertFalse(research["historical_team_run_shadow"]["champion_impact"])

if __name__=="__main__": unittest.main()
