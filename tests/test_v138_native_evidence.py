from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import market
from v11 import v138_book_telemetry as telemetry
from v11 import v138_native_evidence as evidence


class V138NativeEvidenceTests(unittest.TestCase):
    def _state(self,i:int,p:float,y:int,market_name:str="ML"):
        return {"game_pk":str(i),"game_date":f"2026-07-{(i%27)+1:02d}T19:00:00Z","home":"Home","away":"Away",
                "market":market_name,"pick":"Home" if market_name!="TOTAL" else "Over","point":None if market_name=="ML" else 1.5,
                "canonical":True,"phase":"FINAL","observation_at":f"2026-07-{(i%27)+1:02d}T18:00:{i%60:02d}Z",
                "p_model":p,"p_market":p,"probability_interval_low":max(.001,p-.20),
                "probability_interval_high":min(.999,p+.20),"settled_result":"WIN" if y else "LOSS"}

    def test_market_consensus_exposes_per_book_probabilities_without_changing_consensus(self):
        event={"bookmakers":[
            {"key":"pinnacle","last_update":"2026-08-19T12:00:00Z","markets":[{"key":"h2h","last_update":"2026-08-19T12:00:00Z","outcomes":[{"name":"Home","price":1.80},{"name":"Away","price":2.10}]}]},
            {"key":"matchbook","last_update":"2026-08-19T12:00:00Z","markets":[{"key":"h2h","last_update":"2026-08-19T12:00:00Z","outcomes":[{"name":"Home","price":1.90},{"name":"Away","price":2.00}]}]},
        ]}
        with patch.object(market.core,"SHARP_BOOKS",{"pinnacle","matchbook"}),patch.object(market.config,"MAX_SHARP_AGE_MIN",120):
            out=market.sharp_consensus(event,"ML","Home",as_of="2026-08-19T12:10:00Z")
        self.assertEqual(set(out["book_probs"]),{"pinnacle","matchbook"})
        self.assertEqual(out["n"],2);self.assertTrue(0<out["p"]<1)

    def test_book_telemetry_keeps_market_data_out_of_baseball_features(self):
        result={"game_pk":7,"phase":"FINAL","as_of":"2026-08-19T18:00:00Z","ctx":{"home":"Home","away":"Away"},"event":{},
                "options":[{"market":"ML","name":"Home","point":None,"p_baseball_calibrated":.60,"p_market":.57}]}
        fake={"book_probs":{"pinnacle":.58,"matchbook":.56},"book_ages_min":{"pinnacle":5,"matchbook":7}}
        with tempfile.TemporaryDirectory() as td,patch.object(telemetry,"FILE",Path(td)/"books.jsonl"),patch.object(telemetry.market,"sharp_consensus",return_value=fake):
            n=telemetry.capture([result]);rows=telemetry.read(Path(td)/"books.jsonl")
        self.assertEqual(n,1);self.assertEqual(rows[0]["book_probs"]["pinnacle"],.58)
        self.assertTrue(rows[0]["market_probability_only"]);self.assertFalse(rows[0]["baseball_feature"])

    def test_probability_band_gate_uses_group_empirical_rates_not_binary_point_coverage(self):
        rows=[];i=0
        for p,wins in ((.30,18),(.40,24),(.50,30),(.60,36),(.70,42),(.80,48)):
            for j in range(60):
                rows.append(self._state(i,p,1 if j<wins else 0));i+=1
        out=evidence.probability_band_validation(rows,min_n=300,min_bin=30)
        self.assertTrue(out["active"]);self.assertGreaterEqual(out["usable_bins"],5)
        self.assertFalse(out["frequentist_confidence_interval"])

    def test_dynamic_calibration_requires_chronological_oos_improvement(self):
        rows=[]
        for i in range(400):
            high=(i%4)<3;y=1 if high else 0
            # Deliberately under-confident raw probabilities: empirical 75/25 vs model 60/40.
            p=.60 if i%8<4 else .40
            # Align outcomes to 75/25 inside each probability group.
            block=i%4;y=1 if (p>.5 and block<3) or (p<.5 and block==0) else 0
            rows.append(self._state(i,p,y))
        out=evidence.dynamic_calibration_oos(rows,min_n=300)
        self.assertEqual(out["n"],400);self.assertGreaterEqual(out["holdout_n"],60)
        self.assertIsNotNone(out.get("raw_logloss"));self.assertIsNotNone(out.get("calibrated_logloss"))
        self.assertFalse(out["production_applied"])

    def test_learned_book_weights_can_pass_only_on_oos(self):
        states=[];books=[]
        for i in range(400):
            y=1 if i%4<3 else 0
            # Two probability regimes make book A informative and book B neutral.
            pbase=.60 if y else .40
            states.append(self._state(i,pbase,y))
            books.append({"game_pk":str(i),"game_date":states[-1]["game_date"],"market":"ML","phase":"FINAL",
                          "observation_at":states[-1]["observation_at"],"canonical":True,
                          "book_probs":{"book_a":.82 if y else .18,"book_b":.50},"p_market":pbase})
        out=evidence.bookmaker_weights_oos(states,books,min_n=300)
        self.assertTrue(out["active"]);self.assertGreater(out["weights"]["book_a"],out["weights"]["book_b"])
        self.assertGreaterEqual(out["holdout_n"],60);self.assertFalse(out["production_applied"])

    def test_insufficient_native_data_never_closes_any_auto_gate(self):
        rows=[self._state(i,.55,i%2) for i in range(20)]
        report=evidence.build(rows,[])
        self.assertFalse(report["uncertainty_coverage"]["active"])
        self.assertFalse(report["dynamic_calibration"]["active"])
        self.assertFalse(report["bookmaker_weights"]["active"])


if __name__=="__main__":unittest.main()
