from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v11 import context
from v11 import discord_v13
from v11 import extra_innings_v13
from v11 import point_in_time_v13 as pit
from v11 import probability_contract_v13 as contract
from v11 import uncertainty_v13
from v11 import v13_model_health
from v11 import v13_park_runtime
from v11 import v13_probability_surface as surface
from v11 import v138_native_evidence as native_evidence
from v11 import v138_research_integrity


class V1310DeepAuditHardeningTests(unittest.TestCase):
    def _surface_result(self):
        return {
            "ctx": {"home": "Home Club", "away": "Away Club"},
            "canonical_lines": {"TOTAL": 8.5},
            "options": [
                {"market":"ML","name":"Home Club","p_baseball_calibrated":.63,"p_predictive_final":.63,"p_effective":.63,"p_push_model":0.0,"p_market":.60},
                {"market":"ML","name":"Away Club","p_baseball_calibrated":.44,"p_predictive_final":.44,"p_effective":.44,"p_push_model":0.0,"p_market":.40},
                {"market":"RUNLINE","name":"Home Club","point":-1.5,"p_baseball_calibrated":.38,"p_predictive_final":.38,"p_effective":.38,"p_push_model":0.0},
                {"market":"RUNLINE","name":"Away Club","point":+1.5,"p_baseball_calibrated":.67,"p_predictive_final":.67,"p_effective":.67,"p_push_model":0.0},
                {"market":"RUNLINE","name":"Home Club","point":+1.5,"p_baseball_calibrated":.72,"p_predictive_final":.72,"p_effective":.72,"p_push_model":0.0},
                {"market":"RUNLINE","name":"Away Club","point":-1.5,"p_baseball_calibrated":.31,"p_predictive_final":.31,"p_effective":.31,"p_push_model":0.0},
                {"market":"TOTAL","name":"Over","point":8.5,"p_baseball_calibrated":.58,"p_predictive_final":.58,"p_effective":.58,"p_push_model":0.0},
                {"market":"TOTAL","name":"Under","point":8.5,"p_baseball_calibrated":.47,"p_predictive_final":.47,"p_effective":.47,"p_push_model":0.0},
            ],
        }

    def test_probability_surface_reconciles_every_complementary_pair(self):
        result = self._surface_result()
        report = surface.reconcile(result)
        self.assertTrue(report["valid"], report)
        opts = result["options"]
        def p(market, name, point=None):
            for o in opts:
                if o["market"] == market and o["name"] == name and (point is None or o.get("point") == point):
                    return float(o["p_baseball_calibrated"])
            raise AssertionError((market, name, point))
        self.assertAlmostEqual(p("ML","Home Club") + p("ML","Away Club"), 1.0, places=6)
        self.assertAlmostEqual(p("RUNLINE","Home Club",-1.5) + p("RUNLINE","Away Club",+1.5), 1.0, places=6)
        self.assertAlmostEqual(p("RUNLINE","Home Club",+1.5) + p("RUNLINE","Away Club",-1.5), 1.0, places=6)
        self.assertAlmostEqual(p("TOTAL","Over",8.5) + p("TOTAL","Under",8.5), 1.0, places=6)
        self.assertGreaterEqual(p("RUNLINE","Home Club",+1.5), p("RUNLINE","Home Club",-1.5))
        self.assertGreaterEqual(p("RUNLINE","Away Club",+1.5), p("RUNLINE","Away Club",-1.5))

    def test_invalid_probability_fails_closed_instead_of_becoming_fifty_percent(self):
        with self.assertRaises(ValueError):
            contract.clip_probability(float("nan"))
        with self.assertRaises(ValueError):
            contract.clip_probability("not-a-number")

    def test_discord_blocks_incomplete_eight_probability_surface(self):
        result = self._surface_result()
        result["game_pk"] = 1
        result["phase"] = "FINAL"
        result["options"] = [o for o in result["options"] if not (o["market"] == "TOTAL" and o["name"] == "Under")]
        with patch.object(discord_v13.core, "send_embed") as send:
            self.assertFalse(discord_v13.send_game(result, {}))
            send.assert_not_called()

    def test_validated_extra_innings_prior_uses_mature_evidence_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inning.json"
            path.write_text(json.dumps({
                "schema":"test","start":"2021-01-01","end":"2026-01-01",
                "extra_inning_examples":300,
                "extra_inning_prior":{"active":True,"n":300,"home_probability":.497},
            }), encoding="utf-8")
            value, meta = extra_innings_v13.validated_home_prior(path)
            self.assertAlmostEqual(value, .497)
            self.assertTrue(meta["active"])
            path.write_text(json.dumps({"extra_inning_prior":{"active":True,"n":199,"home_probability":.497}}), encoding="utf-8")
            value2, meta2 = extra_innings_v13.validated_home_prior(path)
            self.assertEqual(value2, .5)
            self.assertFalse(meta2["active"])

    def test_pit_distinguishes_operational_from_promotion_grade_capture(self):
        base = {"game_date":"2026-08-19T20:00:00Z","analyzed_at":"2026-08-19T18:00:00Z","features":{}}
        operational = dict(base)
        pit.mark_live_snapshot(operational, operational["analyzed_at"])
        self.assertTrue(operational["point_in_time"])
        self.assertFalse(operational["point_in_time_validation"]["promotion_grade_valid"])

        durable = {**base, "source_replay":"runtime/v13/replays/test.json.gz"}
        pit.mark_live_snapshot(durable, durable["analyzed_at"])
        self.assertTrue(durable["point_in_time"])
        self.assertTrue(durable["point_in_time_validation"]["promotion_grade_valid"])

    def test_weather_cache_is_scoped_to_replay_as_of(self):
        context._WEATHER_CACHE.clear()
        game = {"gameDate":"2026-08-19T23:00:00Z"}
        payload = {"hourly":{
            "time":["2026-08-19T23:00"],"temperature_2m":[20.0],"relative_humidity_2m":[50.0],
            "dew_point_2m":[10.0],"surface_pressure":[1000.0],"precipitation_probability":[0.0],
            "cloud_cover":[20.0],"wind_speed_10m":[8.0],"wind_direction_10m":[180.0],"wind_gusts_10m":[12.0],
        }}
        with patch.object(context.core, "replay_as_of", side_effect=["2026-08-19T18:00:00Z","2026-08-19T19:00:00Z"]), \
             patch.object(context.core, "http_json", return_value=payload) as fetch:
            first = context.weather_for_game(game, "New York Yankees")
            second = context.weather_for_game(game, "New York Yankees")
        self.assertEqual(fetch.call_count, 2)
        self.assertNotEqual(first["forecast_reference_at"], second["forecast_reference_at"])

    def test_native_evidence_never_pools_markets_for_activation(self):
        rows=[]
        for i in range(320):
            rows.append({
                "game_pk":str(i),"game_date":f"2026-07-{(i%27)+1:02d}T19:00:00Z","home":"Home","away":"Away",
                "market":"ML","pick":"Home","canonical":True,"phase":"FINAL","observation_at":f"2026-07-{(i%27)+1:02d}T18:00:{i%60:02d}Z",
                "p_model":.55,"p_market":.53,"probability_interval_low":.35,"probability_interval_high":.75,
                "settled_result":"WIN" if i%2 else "LOSS",
            })
        report=native_evidence.build(rows,[])
        self.assertEqual(report["market_counts"]["ML"],320)
        self.assertEqual(report["market_counts"]["RUNLINE"],0)
        self.assertEqual(report["market_counts"]["TOTAL"],0)
        self.assertFalse(report["uncertainty_coverage"]["active"])
        self.assertFalse(report["dynamic_calibration"]["active"])
        self.assertIn("by_market",report["dynamic_calibration"])

    def test_probability_drift_uses_canonical_side_and_detects_confidence_shift(self):
        states=[]
        for i in range(120):
            p=.51 if i<60 else .70
            month="07" if i<60 else "08"
            day=(i%30)+1
            states.append({"game_pk":str(i),"market":"ML","pick":"Home","home":"Home","p_model":p,
                           "settled_result":"WIN" if i%2 else "LOSS","observation_at":f"2026-{month}-{day:02d}T18:00:00Z"})
            # Complementary away side should be excluded from the drift sample.
            states.append({"game_pk":str(i),"market":"ML","pick":"Away","home":"Home","p_model":1-p,
                           "settled_result":"LOSS" if i%2 else "WIN","observation_at":f"2026-{month}-{day:02d}T18:00:30Z"})
        drift=v13_model_health._probability_drift(states)["ML"]
        self.assertEqual(drift["observations"],120)
        self.assertGreater(drift["confidence_shift"],.10)

    def test_uncertainty_band_is_not_labeled_validated_confidence(self):
        band=uncertainty_v13.empirical_interval(.6,calibration_n=100,phase_n=100,market_n=100)
        self.assertIsNone(band["confidence_level"])
        self.assertIsNone(band["nominal_level"])
        self.assertEqual(band["construction_target_level"],.90)
        self.assertFalse(band["coverage_validated"])

    def test_park_runtime_uses_prior_completed_season_ratio(self):
        result={"ctx":{"home":"Colorado Rockies"},"game":{"venue":{"name":"Coors Field"}}}
        artifact={"seasons":{"2026":{"ALL":{"rows":[{"venue":"Coors Field","runs_index":110.0,"source_method":"test"}],
                                                     "source_window_end_season":2025,"source_window_years":[2023,2024,2025],
                                                     "provider_fallback":False}}}}
        with patch.object(v13_park_runtime.park,"load",return_value=artifact), \
             patch.object(v13_park_runtime.core,"SEASON",2026), \
             patch.dict(v13_park_runtime.core.PARK,{"Colorado Rockies":1.14},clear=False):
            h,a,meta=v13_park_runtime.apply(result,5.7,4.56)
        self.assertTrue(meta["active"])
        self.assertAlmostEqual(meta["factor"],1.10)
        self.assertAlmostEqual(h,5.7*(1.10/1.14))
        self.assertAlmostEqual(a,4.56*(1.10/1.14))

    def test_research_artifacts_bind_to_actual_dataset_content_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            content_hash=hashlib.sha256(b"actual-feature-and-label-bytes").hexdigest()
            manifest=root/"manifest.json"; model=root/"model.json"; validation=root/"validation.json"
            manifest.write_text(json.dumps({"dataset_content_sha256":content_hash,"feature_rows":10,"label_rows":10,"feature_contract_sha256":"abc"}),encoding="utf-8")
            model.write_text(json.dumps({"games":10,"dataset_fingerprint":"legacy-id-only","research_only":True}),encoding="utf-8")
            validation.write_text(json.dumps({"games":10}),encoding="utf-8")
            report=v138_research_integrity.bind(manifest,model,validation)
            self.assertEqual(report["dataset_content_sha256"],content_hash)
            rebound=json.loads(model.read_text(encoding="utf-8"))
            self.assertEqual(rebound["dataset_content_sha256"],content_hash)
            self.assertTrue(rebound["dataset_integrity"]["bound"])
            self.assertFalse(rebound["dataset_integrity"]["legacy_identity_fingerprint_sufficient"])

    def test_generation_fingerprint_moves_with_predictive_behavior(self):
        self.assertTrue(contract.MODEL_GENERATION_FINGERPRINT.startswith("v13.10-gen-"))
        self.assertIn("independent-transfer",contract.MODEL_GENERATION_FINGERPRINT)
        self.assertTrue(math.isfinite(contract.clip_probability(.5)))


if __name__ == "__main__":
    unittest.main()
