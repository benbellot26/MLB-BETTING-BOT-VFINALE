from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from v14.historical_rich_validation import build


class HistoricalRichValidationTests(unittest.TestCase):
    def test_only_embedded_features_are_claimed(self):
        rows=[
            {"game_pk":1,"home_score":5,"away_score":3,"y":1,"starters":{"home_id":10,"away_id":20,"home_prior_ip":50,"away_prior_ip":60},"lineup_known":{"home":1,"away":1},"v9":{"home_mu":4.0,"away_mu":4.0,"p_home":.52},"v10":{"home_mu":4.4,"away_mu":3.8,"p_home":.58}},
            {"game_pk":2,"home_score":2,"away_score":4,"y":0,"starters":{"home_id":11,"away_id":21,"home_prior_ip":20,"away_prior_ip":25},"lineup_known":{"home":0,"away":0},"v9":{"home_mu":4.0,"away_mu":4.0,"p_home":.52},"v10":{"home_mu":3.8,"away_mu":4.2,"p_home":.45}},
        ]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"rows.jsonl";p.write_text("\n".join(json.dumps(r) for r in rows)+"\n",encoding="utf-8")
            out=build(p)
        self.assertEqual(out["rows"],2)
        self.assertEqual(out["coverage"]["both_starter_ids"]["n"],2)
        self.assertEqual(out["coverage"]["both_lineups_known"]["n"],1)
        self.assertEqual(out["evidence"]["statcast"],"NEEDS_RICH_PIT")
        self.assertEqual(out["evidence"]["weather"],"NEEDS_RICH_PIT")
        self.assertEqual(out["role"],"DIAGNOSTIC_ONLY")
        self.assertFalse(out["auto_activation"])


if __name__=="__main__": unittest.main()
