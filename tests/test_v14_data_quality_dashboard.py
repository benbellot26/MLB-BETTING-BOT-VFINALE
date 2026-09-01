from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from v14 import MODEL_GENERATION
from v14.data_quality_dashboard import build


class V14DataQualityDashboardTests(unittest.TestCase):
    def test_generation_mismatch_is_visible_and_never_certifies(self)->None:
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"data").mkdir()
            (root/"data/v14_coverage_report.json").write_text(json.dumps({"model_generation":MODEL_GENERATION,"scheduled_final_trigger":{"first_observation_unique_games":{"observations":11,"eligible_coverage":1.0,"market_fresh_coverage":1.0,"sharp_coverage":1.0,"execution_coverage":1.0}}}),encoding="utf-8")
            (root/"data/v14_betting_certification.json").write_text(json.dumps({"model_generation":"old","certified":True,"betting_status":"BETTING_CERTIFIED"}),encoding="utf-8")
            out=build(root=root)
            self.assertFalse(out["betting_certified"])
            self.assertIn("certification_generation_mismatch_pending_zero_api_reset",out["warnings"])
            self.assertEqual(out["network_calls"],0)
            self.assertFalse(out["feature_ownership"]["market_probability_used_as_feature"])


if __name__=="__main__":unittest.main()
