from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import pipeline_v13
from v11 import probability_contract_v13 as contract
from v11 import v13_daily_tracking as tracking
from v11 import v13_daily_postmortem as postmortem
from v11 import v13_exact_transfer_evidence as exact_evidence
from v11 import v13_tracking_sync
from v11 import v13_run_mean_prior


class V1351AuditFixesTest(unittest.TestCase):
    def test_tracking_key_is_immutable_by_phase_and_asof(self):
        opt={"market":"ML","name":"Home","point":None}
        early={"game_pk":1,"phase":"EARLY","as_of":"2026-08-17T12:00:00+00:00"}
        final={"game_pk":1,"phase":"FINAL","as_of":"2026-08-17T18:00:00+00:00"}
        self.assertNotEqual(tracking._key(early,opt),tracking._key(final,opt))
        events=[
            {"tracking_key":tracking._key(early,opt),"event_type":"MODEL_SNAPSHOT","phase":"EARLY","p_model":.55},
            {"tracking_key":tracking._key(final,opt),"event_type":"MODEL_SNAPSHOT","phase":"FINAL","p_model":.61},
        ]
        state=tracking.fold(events)
        self.assertEqual(len(state),2)
        self.assertEqual({x["phase"] for x in state.values()},{"EARLY","FINAL"})

    def test_tracking_sync_keeps_latest_per_game_and_phase(self):
        rows=[
            {"game_pk":1,"phase":"EARLY","analyzed_at":"2026-08-17T10:00:00+00:00","game_date":"2026-08-17T20:00:00+00:00","options":[{}]},
            {"game_pk":1,"phase":"EARLY","analyzed_at":"2026-08-17T11:00:00+00:00","game_date":"2026-08-17T20:00:00+00:00","options":[{}]},
            {"game_pk":1,"phase":"FINAL","analyzed_at":"2026-08-17T19:00:00+00:00","game_date":"2026-08-17T20:00:00+00:00","options":[{}]},
        ]
        with patch.object(v13_tracking_sync.journal,"load_rows",return_value=rows):
            got=v13_tracking_sync._latest_pregame_rows()
        self.assertEqual(len(got),2)
        self.assertEqual({r["phase"] for r in got},{"EARLY","FINAL"})
        early=next(r for r in got if r["phase"]=="EARLY")
        self.assertEqual(early["analyzed_at"],"2026-08-17T11:00:00+00:00")

    def test_postmortem_uses_latest_within_each_phase(self):
        base={"game_pk":1,"market":"ML","pick":"Home","home":"Home","away":"Away","point":None,"settled_result":"WIN"}
        states=[
            {**base,"phase":"EARLY","observation_at":"2026-08-17T10:00:00+00:00","p_model":.51},
            {**base,"phase":"EARLY","observation_at":"2026-08-17T11:00:00+00:00","p_model":.54},
            {**base,"phase":"FINAL","observation_at":"2026-08-17T19:00:00+00:00","p_model":.62},
        ]
        early=postmortem._choose_independent(states,"EARLY")
        latest=postmortem._choose_independent(states)
        self.assertEqual(len(early),1)
        self.assertEqual(early[0]["p_model"],.54)
        self.assertEqual(latest[0]["p_model"],.62)

    def test_reliability_lookup_stays_in_raw_probability_space(self):
        model={"calibrators":{
            "PHASE:FINAL:ML":{
                "active":True,"method":"platt","a":-1.0,"b":1.0,"n":500,
                "reliability_bins":[
                    {"lo":.35,"hi":.45,"sigma":.02},
                    {"lo":.60,"hi":.65,"sigma":.09},
                ],
            },
            "MARKET:ML":{"n":500},
        }}
        p=pipeline_v13.ProbabilityPipelineV13(model)
        opt={"market":"ML","p_learned":.62,"p_market":.50,"sharp_weight":0.0}
        p.transform_option(opt,"FINAL",data_quality=1.0)
        self.assertNotAlmostEqual(opt["p_baseball_calibrated"],.62)
        self.assertEqual(opt["reliability_source_v13"],"PHASE:FINAL:ML")
        self.assertAlmostEqual(opt["probability_uncertainty_v13"]["empirical_reliability_sigma"],.09)

    def test_final_run_mean_exact_transfer_excludes_early_late(self):
        rows=[
            {"game_pk":1,"game_date":"2026-08-17T20:00:00Z","phase":"EARLY","analyzed_at":"2026-08-17T10:00:00Z","projected_home_runs":4.2,"projected_away_runs":4.0,"home_score":5,"away_score":4},
            {"game_pk":1,"game_date":"2026-08-17T20:00:00Z","phase":"FINAL","analyzed_at":"2026-08-17T19:00:00Z",
             "projected_home_runs":4.4,"projected_away_runs":4.1,
             "validation_baseline_home_runs":4.4,"validation_baseline_away_runs":4.1,
             "validation_baseline_dispersion":7.5,
             "validation_baseline_model_generation":contract.MODEL_GENERATION_FINGERPRINT,
             "point_in_time":True,"features_from_postgame":False,
             "home_score":5,"away_score":4},
            {"game_pk":2,"game_date":"2026-08-17T21:00:00Z","phase":"LATE","analyzed_at":"2026-08-17T19:00:00Z","projected_home_runs":4.0,"projected_away_runs":3.9,"home_score":3,"away_score":2},
        ]
        contract.attach_contract(rows[1])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"exact.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in rows)+"\n",encoding="utf-8")
            replay_rows=exact_evidence.load_exact_final_rows(replay_path=path,include_native=False)
            with patch.object(v13_run_mean_prior.exact_evidence,"load_exact_final_rows",return_value=replay_rows):
                got=v13_run_mean_prior._exact_rows()
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["phase"],"FINAL")
        self.assertAlmostEqual(got[0]["home_mu"],4.4)
        self.assertAlmostEqual(got[0]["away_mu"],4.1)
        self.assertAlmostEqual(got[0]["dispersion"],7.5)

    def test_stale_calibration_guard_fails_closed(self):
        from v11 import v13_entry
        with patch.object(v13_entry.calibration_v13,"load_model",return_value={"schema":"v13-baseball-calibration-model-v1","baseball_only":True}):
            with self.assertRaises(SystemExit):
                v13_entry._assert_v135_calibration_artifact()
        with patch.object(v13_entry.calibration_v13,"load_model",return_value={"schema":"v13-baseball-calibration-model-v2","baseball_only":True,"model_generation":"older"}):
            with self.assertRaises(SystemExit):
                v13_entry._assert_v135_calibration_artifact()
        with patch.object(v13_entry.calibration_v13,"load_model",return_value={"schema":"v13-baseball-calibration-model-v2","baseball_only":True,"model_generation":contract.MODEL_GENERATION_FINGERPRINT,"status":"EMPTY_NATIVE_BASELINE"}):
            v13_entry._assert_v135_calibration_artifact()


if __name__ == "__main__":
    unittest.main()
