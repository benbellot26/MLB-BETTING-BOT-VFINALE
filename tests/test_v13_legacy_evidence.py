import tempfile
import unittest
from pathlib import Path

from v11 import calibration_baseball_v13 as cal
from v11 import v13_train


class LegacyEvidenceTests(unittest.TestCase):
    def test_inactive_identity_exposes_market_evidence_n_without_changing_p(self):
        model={"calibrators":{
            "PHASE:FINAL:ML":{"active":False,"method":"identity","n":5},
            "MARKET:ML":{"active":False,"method":"identity","n":29},
            "GLOBAL":{"active":False,"method":"identity","n":49},
        }}
        p,source,n=cal.calibrate(.528,"ML","FINAL",model)
        self.assertAlmostEqual(p,.528)
        self.assertEqual(source,"identity")
        self.assertEqual(n,29)

    def test_active_phase_calibrator_still_has_priority(self):
        model={"calibrators":{
            "PHASE:FINAL:ML":{"active":True,"method":"platt","a":0.0,"b":1.0,"n":350},
            "MARKET:ML":{"active":False,"method":"identity","n":500},
        }}
        p,source,n=cal.calibrate(.61,"ML","FINAL",model)
        self.assertAlmostEqual(p,.61,places=6)
        self.assertEqual(source,"PHASE:FINAL:ML")
        self.assertEqual(n,350)

    def test_exact_backfill_loader_rejects_postgame_features(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"x.jsonl"
            good='{"schema":"v13-point-in-time-backfill-v1","point_in_time":true,"features_from_postgame":false,"home_score":3,"away_score":2}'
            bad='{"schema":"v13-point-in-time-backfill-v1","point_in_time":true,"features_from_postgame":true,"home_score":3,"away_score":2}'
            p.write_text(good+'\n'+bad+'\n',encoding='utf-8')
            rows=v13_train._load_exact_backfill(p)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["v13_evidence_tier"],"A_EXACT_REPLAY")


if __name__ == "__main__":
    unittest.main()
