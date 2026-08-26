from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from v14.historical_team_shadow import evaluate, load


def _artifact():
    return {"schema":"pulsar-v14-historical-team-run-candidate-v1","status":"HISTORICAL_VALIDATED_SHADOW","auto_activation":False,"champion_impact":False,"native_live_confirmation_required":True,"source_run_id":1,"frozen_at":"2026-08-26T16:51:01+00:00","dataset":{"dataset_content_sha256":"a","feature_contract_sha256":"b"},"parameters":{"season_prior_games":15.0,"recent14_weight":.1,"recent7_weight":0.0,"offense_weight":.45,"home_advantage_runs":.08,"park_weight":0.0}}


def _team(rf,ra):
    return {"season_to_date":{"games":50,"runs_for_pg":rf,"runs_against_pg":ra},"last_14_games":{"games":14,"runs_for_pg":rf+.1,"runs_against_pg":ra-.1},"last_7_games":{"games":7,"runs_for_pg":rf,"runs_against_pg":ra},"last_30_games":{"games":30,"runs_for_pg":rf,"runs_against_pg":ra}}


def _history():
    return {"status":"READY_SHADOW","point_in_time":True,"home":_team(4.8,4.1),"away":_team(4.2,4.7)}


def _prediction():
    return {"game_pk":"1","game_date":"2026-08-27T20:00:00Z","analyzed_at":"2026-08-27T18:00:00Z","phase":"FINAL","home":"Home","away":"Away","model_generation":"g","total_line":8.5,"run_projection":{"home_mu":4.55,"away_mu":4.15,"dispersion":7.5,"environment_sigma":.08,"extra_innings_home_probability":.496},"probabilities":{"home_ml":.55,"away_ml":.45,"home_minus_1_5":.40,"away_plus_1_5":.60,"home_plus_1_5":.69,"away_minus_1_5":.31,"over":.52,"under":.48}}


class HistoricalTeamShadowTests(unittest.TestCase):
    def test_repository_artifact_is_hash_bound_and_enabled_for_shadow(self):
        out=load(); self.assertEqual(out.get("status"),"HISTORICAL_VALIDATED_SHADOW"); self.assertFalse(out.get("champion_impact"))

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ap=Path(td)/"a.json";mp=Path(td)/"m.json";a=_artifact();ap.write_text(json.dumps(a),encoding="utf-8");mp.write_text(json.dumps({"dataset_content_sha256":"x","feature_contract_sha256":"b"}),encoding="utf-8")
            self.assertEqual(load(ap,mp),{})

    def test_shadow_changes_runs_and_probabilities_without_champion_impact(self):
        out=evaluate(_prediction(),_history(),artifact=_artifact())
        self.assertEqual(out["status"],"READY_SHADOW"); self.assertFalse(out["champion_impact"]); self.assertFalse(out["auto_activation"])
        self.assertNotEqual(out["candidate_run_projection"]["home_mu"],out["champion_run_projection"]["home_mu"])
        self.assertAlmostEqual(out["candidate_probabilities"]["home_ml"]+out["candidate_probabilities"]["away_ml"],1.0)
        self.assertIn("home_ml",out["probability_delta"])

    def test_missing_pit_history_collects_instead_of_guessing(self):
        out=evaluate(_prediction(),{"status":"COLLECTING","point_in_time":True},artifact=_artifact()); self.assertEqual(out["status"],"COLLECTING")


if __name__=="__main__":unittest.main()
