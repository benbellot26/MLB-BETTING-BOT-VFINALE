import tempfile
from pathlib import Path
import unittest

from v14 import MODEL_GENERATION
from v14.native_payload import authorize_payload, build_native_discord_payload
from v14.tracking import append_snapshot, _read_jsonl


class V14EndToEndTrackingTests(unittest.TestCase):
    def test_market_state_survives_candidate_payload_tracking(self):
        candidate={
            "role":"CANDIDATE_NON_PUBLISHING","native_acquisition":True,"legacy_acquisition_adapter":False,"market_probability_used_as_feature":False,
            "target_date":"2026-08-25","analyzed_at":"2026-08-25T12:00:00Z","coverage":{"matched_odds_games":1,"priced_games":1},
            "results":[{
                "game_pk":"123","game_date":"2026-08-25T18:00:00Z","analyzed_at":"2026-08-25T12:00:00Z","phase":"EARLY","home":"Home","away":"Away","ctx":{},"canonical_lines":{"TOTAL":8.5},"line_selection":{"line":8.5,"market_price_used_as_feature":False},
                "market_snapshot":{"schema":"pulsar-v14-market-snapshot-v2","markets":{"ML":{"selections":{"home":{"price":1.90},"away":{"price":2.00}}}}},
                "market_diagnostics":{"schema":"pulsar-v14-market-diagnostics-v1","markets":{"ML":{"selections":{"home":{"edge_pp":3.0,"expected_value_per_unit":.04}}}}},
                "v14_prediction":{"role":"PRODUCTION","model_generation":MODEL_GENERATION,"game_pk":"123","game_date":"2026-08-25T18:00:00Z","analyzed_at":"2026-08-25T12:00:00Z","home":"Home","away":"Away","phase":"EARLY","total_line":8.5,"market_probability_used_as_feature":False,"run_projection":{"home_mu":4.6,"away_mu":4.0,"total_line":8.5},"probabilities":{"away_ml":.44,"home_ml":.56,"away_plus_1_5":.61,"home_minus_1_5":.39,"home_plus_1_5":.70,"away_minus_1_5":.30,"over":.52,"under":.48}},
            }],
        }
        production=authorize_payload(build_native_discord_payload(candidate),production_authorized=True)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"predictions.jsonl"; self.assertEqual(append_snapshot(production,path),1); row=_read_jsonl(path)[0]
        self.assertEqual(row["market_snapshot"]["markets"]["ML"]["selections"]["home"]["price"],1.90)
        self.assertEqual(row["market_diagnostics"]["markets"]["ML"]["selections"]["home"]["edge_pp"],3.0)
        self.assertFalse((row["market_snapshot"] or {}).get("market_probability_used_as_feature",False))

if __name__=="__main__": unittest.main()
