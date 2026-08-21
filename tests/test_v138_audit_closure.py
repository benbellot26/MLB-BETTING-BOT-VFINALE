from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from v11 import v138_advanced_research as advanced
from v11 import v138_audit_closure as closure
from v11 import v138_audit_features as features
from v11 import v138_dataset_store as store
from v11 import v138_live_change as live
from v11 import v138_research_models as models
from v11 import v138_validation as validation
from v11 import v13_discord_delivery as delivery


class V138AuditClosureTests(unittest.TestCase):
    def _row(self, i: int, season: int = 2024):
        hbase=4.0+(i%7)*.12;abase=3.9+(i%5)*.13
        return {
            "game_pk":str(i),"game_date":f"{season}-06-{(i%27)+1:02d}T19:00:00Z","official_date":f"{season}-06-{(i%27)+1:02d}",
            "season":season,"home":"H","away":"A","home_id":1+(i%4),"away_id":11+(i%4),
            "cohort":"HISTORICAL_RECONSTRUCTED_FREE","native_live":False,"promotion_eligible":False,
            "features":{
                "home_team_form":{"season_to_date":{"games":50,"runs_for_pg":hbase,"runs_against_pg":4.3,"win_pct":.52},
                    "last_30_games":{"games":30,"runs_for_pg":hbase+.1},"last_14_games":{"games":14,"runs_for_pg":hbase+.15},
                    "last_7_games":{"games":7,"runs_for_pg":hbase+.2},"rest_days":1},
                "away_team_form":{"season_to_date":{"games":50,"runs_for_pg":abase,"runs_against_pg":4.5,"win_pct":.48},
                    "last_30_games":{"games":30,"runs_for_pg":abase+.05},"last_14_games":{"games":14,"runs_for_pg":abase+.1},
                    "last_7_games":{"games":7,"runs_for_pg":abase+.15},"rest_days":0},
                "park_prior":{"available":True,"ALL":101,"LHB":103,"RHB":99},
            },
        }

    def _dataset(self,n=220):
        rows=[];labels=[]
        for i in range(n):
            season=2023+i//90
            r=self._row(i,season);rows.append(r)
            x=models.vectorize(r);hs=max(0,round(1.05*x[16]+.15*(i%3)));aws=max(0,round(.98*x[17]+.12*((i+1)%3)))
            labels.append({"game_pk":str(i),"home_score":hs,"away_score":aws,"home_win":int(hs>aws),"total_runs":hs+aws})
        return rows,labels

    def test_offense_shrinkage_and_missing_optional_context_are_neutral(self):
        off=features.offense_talent({"last_7_games":{"games":2,"runs_for_pg":8.0}})
        self.assertGreater(off["runs_per_game"],4.45);self.assertLess(off["runs_per_game"],8.0)
        self.assertEqual(features.defense_factor({})["runs_allowed_factor"],1.0)
        self.assertEqual(features.baserunning_factor({})["offense_factor"],1.0)
        self.assertEqual(features.catcher_framing_factor({})["runs_allowed_factor"],1.0)
        self.assertEqual(features.umpire_factor({})["run_factor"],1.0)

    def test_starter_pitch_mix_lineup_bullpen_and_opener_features(self):
        s=features.starter_skill({"era":3.2,"whip":1.1},{"k_rate":.28,"bb_rate":.06,"xwoba":.285,"hard_hit_rate":.32,"barrel_rate":.055,"avg_velocity":95})
        self.assertLess(s["run_prevention_multiplier"],1.0)
        pm=features.pitch_mix_matchup({"FF":.6,"SL":.4},[{"pitch_values":{"FF":1.05,"SL":.95}}])
        self.assertTrue(pm["available"]);self.assertAlmostEqual(sum(pm["pitch_mix"].values()),1.0)
        lu=features.lineup_strength([{"ops":.800,"pa":300} for _ in range(9)])
        self.assertTrue(lu["confirmed"]);self.assertGreater(lu["factor"],1.0)
        bp=features.classify_bullpen_roles([{"id":1,"saves":20,"pitches_3d":10},{"id":2,"holds":15,"pitches_3d":20},{"id":3,"pitches_3d":50}])
        self.assertEqual(bp["roles"]["closer"][0]["id"],1)
        self.assertTrue(features.detect_opener({"starts":8,"innings":14})["bullpen_game"])

    def test_vector_has_no_target_label_and_reconstructed_candidate_cannot_promote(self):
        r=self._row(1);r["home_score"]=99;r["away_score"]=0
        v=models.vectorize(r);self.assertEqual(len(v),len(models.FEATURE_NAMES))
        r2=dict(r);r2["home_score"]=-99;r2["away_score"]=50
        self.assertEqual(v,models.vectorize(r2))
        rows,labels=self._dataset();artifact=models.fit(rows,labels)
        self.assertEqual(artifact["status"],"TRAINED_RESEARCH_ONLY")
        self.assertFalse(artifact["promotion_eligible"])
        self.assertTrue(artifact["holdout_isolation"])
        self.assertGreater(artifact["validation_games"],0)
        p=models.predict(artifact,rows[-1]);self.assertTrue(p["available"]);self.assertFalse(p["affects_champion"])

    def test_glm_gam_gbdt_hierarchy_and_ensemble_are_finite(self):
        rows,labels=self._dataset();artifact=models.fit(rows,labels)
        self.assertEqual(set((artifact.get("models") or {}).keys()),{"glm","gam","gbdt","hierarchical"})
        self.assertIn("naive",artifact.get("ensemble_weights") or {})
        self.assertAlmostEqual(sum((artifact.get("ensemble_weights") or {}).values()),1.0,places=6)
        for block in (artifact.get("validation_metrics") or {},artifact.get("holdout_metrics") or {}):
            for metric in block.values():
                for key,val in metric.items():self.assertTrue(val is None or math.isfinite(float(val)),key)

    def test_bootstrap_calibration_book_weights_and_extra_innings_keep_evidence_floors(self):
        y=[i%2 for i in range(80)];a=[.60 if x else .40 for x in y];b=[.55 if x else .45 for x in y]
        ci=validation.bootstrap_difference(y,a,b,validation.brier,iterations=120);self.assertTrue(ci["available"]);self.assertLess(ci["difference"],0)
        self.assertFalse(validation.learn_bookmaker_weights([{"outcome":1,"book_probs":{"a":.5,"b":.5}}]*20)["active"])
        self.assertFalse(validation.learn_extra_innings_home_prior([{"extra_innings":True,"home_win":1}]*50)["active"])
        self.assertFalse(advanced.dynamic_calibration([{"outcome":1,"p_model":.6}]*50)["active"])

    def test_material_live_change_republishes_starter_personnel_or_lineup_order(self):
        base={"game_pk":7,"ctx":{"home_starter":{"id":1},"away_starter":{"id":2},
              "home_lineup":{"players":[{"id":x} for x in range(10,19)]},"away_lineup":{"players":[{"id":x} for x in range(20,29)]}}}
        prev={"analysis_signature":live.signature(base),"personnel_state":live.personnel_state(base)}
        self.assertFalse(live.classify(prev,base)["changed"])
        order={"game_pk":7,"ctx":dict(base["ctx"])};order["ctx"]["home_lineup"]={"players":[{"id":x} for x in [11,10,12,13,14,15,16,17,18]]}
        ch=live.classify(prev,order);self.assertTrue(ch["changed"]);self.assertTrue(ch["critical"])
        starter={"game_pk":7,"ctx":dict(base["ctx"])};starter["ctx"]["home_starter"]={"id":99}
        self.assertTrue(live.classify(prev,starter)["critical"])

    def test_delivery_checkpoint_is_backward_compatible_and_republishes_critical_change(self):
        base={"game_pk":7,"ctx":{"home_starter":{"id":1},"away_starter":{"id":2},"home_lineup":{"players":[{"id":x} for x in range(10,19)]},"away_lineup":{"players":[{"id":x} for x in range(20,29)]}}}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"delivery.json";delivery.mark_sent(7,analysis_signature=live.signature(base),personnel_state=live.personnel_state(base),path=p)
            self.assertFalse(delivery.delivery_decision(7,base,p)["send"])
            changed={"game_pk":7,"ctx":dict(base["ctx"])};changed["ctx"]["away_starter"]={"id":77}
            d=delivery.delivery_decision(7,changed,p);self.assertTrue(d["send"]);self.assertTrue(d["critical_change"])

    def test_dataset_checksums_and_reproducibility_manifest(self):
        rows,labels=self._dataset(30)
        m=validation.reproducibility_manifest(rows,labels,code_sha="abc",seed=138);self.assertTrue(m["reproducible"])
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"x";p.write_text("abc",encoding="utf-8")
            self.assertEqual(store.sha256_file(p),"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_advanced_layers_are_research_only_and_fail_closed_without_data(self):
        self.assertFalse(advanced.fit_inning_profile([])["active"])
        self.assertFalse(advanced.fit_contextual_dispersion([])["active"])
        regimes=advanced.fit_season_regimes([{"season":2025,"total_runs":9},{"season":2026,"total_runs":7}]);self.assertFalse(regimes["promotion_eligible"])
        inter=advanced.nonlinear_interactions({"lineup_factor":1.1,"starter_multiplier":.9,"park_factor":1.02,"weather_factor":1.01})
        self.assertIn("four_way",inter)

    def test_52_point_registry_closes_engineering_and_allows_evidence_to_progress(self):
        d=closure.build();self.assertEqual(d["total_points"],52);self.assertEqual(d["engineering_closed"],52);self.assertEqual(d["engineering_open"],0)
        self.assertIn("never lowered",d["policy"]);self.assertTrue(all(p["engineering_closed"] for p in d["points"]))
        pending=sum(not bool(p["evidence_closed"]) for p in d["points"])
        self.assertEqual(pending,d["evidence_gates_pending"])
        by_id={p["id"]:p for p in d["points"]}
        # These two use stable free historical outcome-only evidence and should
        # remain closed once their persisted MLB evidence artifacts cross N.
        if by_id[21]["evidence_note"].startswith("authenticated free MLB extra-inning examples=1220"):
            self.assertTrue(by_id[21]["evidence_closed"])
        if by_id[49]["evidence_note"].startswith("authenticated free MLB inning-profile games=360"):
            self.assertTrue(by_id[49]["evidence_closed"])


if __name__=="__main__":unittest.main()
