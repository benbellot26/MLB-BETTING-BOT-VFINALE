import tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from v11 import core, market, selector, storage, data_quality, pro_model
from v11 import engine_v12 as engine
from v11 import journal


def fresh(): return datetime.now(timezone.utc).isoformat()


class V12Tests(unittest.TestCase):
    def test_score_distribution(self):
        hp,ap=engine.score_matrix(4.6,4.1)
        self.assertAlmostEqual(sum(hp),1,places=9); self.assertAlmostEqual(sum(ap),1,places=9)
        self.assertGreater(engine.prob_home_win(5,4),.5)

    def test_push_complements(self):
        hw,hp=engine.prob_cover_parts(4.5,4,"home",-1.0); aw,ap=engine.prob_cover_parts(4.5,4,"away",1.0)
        self.assertAlmostEqual(hw+aw+hp,1,places=6); self.assertAlmostEqual(hp,ap,places=9)
        ow,op=engine.prob_total_parts(4.5,4,"over",9); uw,up=engine.prob_total_parts(4.5,4,"under",9)
        self.assertAlmostEqual(ow+uw+op,1,places=6); self.assertAlmostEqual(op,up,places=9)

    def test_uncertainty_raises_required_price(self):
        a={"p_effective":.62,"p_win":.62,"p_push":0,"model_uncertainty":.005,"winamax_eval":{"price":2}}
        b=dict(a); b["model_uncertainty"]=.05
        self.assertGreater(selector.required_price(b),selector.required_price(a))

    def test_push_aware_kelly(self):
        rec={"p_effective":.60,"p_win":.54,"p_push":.10,"model_uncertainty":0,"winamax_eval":{"price":2}}
        g=selector.value_gate(rec); self.assertGreaterEqual(g["p_push"],.10); self.assertGreaterEqual(selector.full_kelly(rec,g),0)
        bad={"p_effective":.45,"p_win":.45,"p_push":0,"model_uncertainty":0,"winamax_eval":{"price":2}}
        self.assertEqual(selector.full_kelly(bad),0)

    def test_missing_sharp_timestamp_is_excluded(self):
        event={"bookmakers":[{"key":"pinnacle","markets":[{"key":"h2h","outcomes":[{"name":"H","price":2},{"name":"A","price":2}]}]}]}
        old=set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS={"pinnacle"}; c=market.sharp_consensus(event,"ML","H")
            self.assertEqual(c["n"],0); self.assertEqual(c["excluded"][0]["reason"],"timestamp_missing")
        finally: core.SHARP_BOOKS=old

    def test_stale_sharp_is_excluded(self):
        stale=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        event={"bookmakers":[{"key":"pinnacle","last_update":stale,"markets":[{"key":"h2h","outcomes":[{"name":"H","price":2},{"name":"A","price":2}]}]}]}
        old=set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS={"pinnacle"}; c=market.sharp_consensus(event,"ML","H")
            self.assertEqual(c["n"],0); self.assertEqual(c["excluded"][0]["reason"],"stale")
        finally: core.SHARP_BOOKS=old

    def test_fresh_devig(self):
        event={"bookmakers":[{"key":"pinnacle","last_update":fresh(),"markets":[{"key":"spreads","outcomes":[{"name":"H","point":-1.5,"price":2},{"name":"A","point":1.5,"price":1.9}]}]}]}
        old=set(core.SHARP_BOOKS)
        try:
            core.SHARP_BOOKS={"pinnacle"}; h=market.sharp_consensus(event,"RUNLINE","H",-1.5); a=market.sharp_consensus(event,"RUNLINE","A",1.5)
            self.assertEqual(h["n"],1); self.assertAlmostEqual(h["p"]+a["p"],1,places=9)
        finally: core.SHARP_BOOKS=old

    def _result(self,phase="FINAL"):
        return {"game_pk":1,"phase":phase,"ctx":{"home_sp":"HS","away_sp":"AS","home_lineup":{"count":9},"away_lineup":{"count":9},
                "home_starter":{"sample_weight":1},"away_starter":{"sample_weight":1}},
                "features":{"weather":{"available":True},"bullpen":{"coverage":1}},"con":{"n":3,"max_age_min":1}}

    def test_data_quality_final_blocker(self):
        r=self._result(); r["ctx"]["away_lineup"]["count"]=2
        rec={"refs":3,"sharp_max_age_min":1,"winamax_eval":{"price":2}}
        q=data_quality.assess(r,rec); self.assertFalse(q["eligible"]); self.assertIn("final_lineup_incomplete",q["blockers"])

    def test_data_quality_complete(self):
        q=data_quality.assess(self._result(),{"refs":3,"sharp_max_age_min":1,"winamax_eval":{"price":2}})
        self.assertTrue(q["eligible"]); self.assertGreaterEqual(q["score"],.68)

    def test_ledger_idempotency(self):
        old=storage.BET_LEDGER_FILE
        with tempfile.TemporaryDirectory() as td:
            storage.BET_LEDGER_FILE=Path(td)/"ledger.jsonl"
            result={"game_pk":11,"ctx":{"home":"H","away":"A"}}
            rec={"market":"ML","name":"H","point":None,"p_effective":.6,"p_win":.6,"p_push":0,"model_uncertainty":.01,"data_quality":{"score":1},
                 "winamax_eval":{"official_selected":True,"official_units":1,"stake_eur":.5,"price":1.9}}
            c={"result":result,"rec":rec}
            self.assertEqual(storage.record_selected_bets([c],None,"r1",fresh(),"2026-08-14"),1)
            self.assertEqual(storage.record_selected_bets([c],None,"r2",fresh(),"2026-08-14"),0)
        storage.BET_LEDGER_FILE=old

    def test_settlement_push(self):
        row={"result_status":"FINAL","home":"H","away":"A","home_score":4,"away_score":3}
        opt={"market":"RUNLINE","name":"A","point":1,"p_effective":.55}; journal.settle_option(opt,row); self.assertEqual(opt["result"],"PUSH")

    def test_calibration_fallback(self):
        p,u,src=pro_model.calibrate("ML",.61,{"active":False})
        self.assertAlmostEqual(p,.61); self.assertGreater(u,0); self.assertEqual(src,"uncalibrated")

    def test_small_candidate_does_not_activate(self):
        c=pro_model.build_candidate([]); self.assertFalse(c["passes"]); self.assertFalse(c["residual"]["active"])


if __name__=="__main__":unittest.main()
