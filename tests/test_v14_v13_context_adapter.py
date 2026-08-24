import unittest

from v14.v13_context_adapter import adapt_feature_row


class V13ContextAdapterTests(unittest.TestCase):
    def test_normalizes_v13_bullpen_and_pitch_matchup_without_mutating_source(self):
        row = {
            "point_in_time": True,
            "features": {
                "bullpen": {
                    "home": {
                        "relievers": [{
                            "id": 1,
                            "pitches_3d": 52,
                            "appearances_recent": 3,
                            "days_used": 3,
                        }]
                    }
                }
            },
            "rich_modules": {
                "home": {"pitch_matchup": {"available": True, "factor": 1.04}}
            },
        }
        adapted = adapt_feature_row(row)
        reliever = adapted["features"]["bullpen"]["home"]["relievers"][0]
        self.assertEqual(reliever["pitches_last_3d"], 52)
        self.assertEqual(reliever["uses_last_3d"], 3)
        self.assertTrue(reliever["taxed"])
        self.assertEqual(adapted["rich_modules"]["home_lineup_pitch_matchup"]["factor"], 1.04)
        self.assertNotIn("pitches_last_3d", row["features"]["bullpen"]["home"]["relievers"][0])
        self.assertFalse(adapted["v14_adapter"]["postgame_data_added"])


if __name__ == "__main__":
    unittest.main()
