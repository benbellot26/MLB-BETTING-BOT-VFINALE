from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from v11.v123_runtime import activate

activate()

from v11 import config, core, pro_model, selector
from v11 import engine_v12 as engine
from v11 import methodology_v123 as m
from v11 import v123_bootstrap as hb


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


class V123AuditTests(unittest.TestCase):
    def test_generation_isolated_from_v122(self):
        self.assertTrue(config.VERSION.startswith("12.3"))
        self.assertEqual(config.SCHEMA_VERSION, "v12-3-professional-v1")
        self.assertEqual(config.FEATURE_SCHEMA_VERSION, "v12-3-features-v1")

    def test_event_matching_uses_start_time_for_doubleheader(self):
        day = datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc)
        games = [
            {"gamePk": 1, "gameDate": iso(day), "teams": {"home": {"team": {"name": "Boston Red Sox"}}, "away": {"team": {"name": "New York Yankees"}}}},
            {"gamePk": 2, "gameDate": iso(day+timedelta(hours=5)), "teams": {"home": {"team": {"name": "Boston Red Sox"}}, "away": {"team": {"name": "New York Yankees"}}}},
        ]
        events = [
            {"id": "late", "home_team": "Boston Red Sox", "away_team": "New York Yankees", "commence_time": iso(day+timedelta(hours=5, minutes=4))},
            {"id": "early", "home_team": "Boston Red Sox", "away_team": "New York Yankees", "commence_time": iso(day+timedelta(minutes=3))},
        ]
        matched = core.match_odds_events(games, events)
        self.assertEqual(matched["1"]["id"], "early")
        self.assertEqual(matched["2"]["id"], "late")

    def test_event_matching_fails_closed_on_true_time_tie(self):
        t = datetime(2026, 8, 14, 18, tzinfo=timezone.utc)
        game = {"gamePk": 1, "gameDate": iso(t), "teams": {"home": {"team": {"name": "H"}}, "away": {"team": {"name": "A"}}}}
        events = [
            {"id": "x", "home_team": "H", "away_team": "A", "commence_time": iso(t-timedelta(minutes=10))},
            {"id": "y", "home_team": "H", "away_team": "A", "commence_time": iso(t+timedelta(minutes=10))},
        ]
        self.assertEqual(core.match_odds_events([game], events), {})

    def test_winamax_execution_requires_fresh_timestamp(self):
        now = datetime.now(timezone.utc)
        base = {"key": core.WINAMAX_KEY, "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": 1.91}, {"name": "A", "price": 1.91}]}]}
        fresh = {"bookmakers": [{**base, "last_update": iso(now-timedelta(minutes=2))}]}
        stale = {"bookmakers": [{**base, "last_update": iso(now-timedelta(minutes=config.V123_MAX_WINAMAX_AGE_MIN+2))}]}
        self.assertAlmostEqual(core.winamax_price(fresh, "ML", "H"), 1.91)
        self.assertIsNone(core.winamax_price(stale, "ML", "H"))

    def test_enhanced_starter_changes_structural_run_mean(self):
        ctx = {"home_starter": {"era": 4.35, "whip": 1.32}, "away_starter": {"era": 4.35, "whip": 1.32}}
        hp = {"era": 4.35}
        ap = {"era": 4.35}
        stronger_home, stronger_away, info = m._rescale_structural_for_v123_starters(
            4.5, 4.5, ctx,
            {"era": 3.0, "whip": 1.05},
            {"era": 6.0, "whip": 1.60}, hp, ap,
        )
        self.assertGreater(stronger_home, 4.5)
        self.assertLess(stronger_away, 4.5)
        self.assertEqual(info["baseline_schema"], "v12.3-structural-v1")

    def _active_native_bootstrap(self):
        return {
            "schema": hb.SCHEMA, "version": hb.VERSION, "active": True,
            "eligible_for_final_prior": True, "status": "PASS",
            "run_correction": {
                "active": True,
                "home": {"mean_mu": 4.5, "intercept": .20, "slope": 0.0},
                "away": {"mean_mu": 4.5, "intercept": -.10, "slope": 0.0},
            },
            "dispersion": {"active": True, "value": 3.2},
            "environment": {"active": True, "sigma": .05},
            "metadata": {"baseline_schema": hb.BASELINE_SCHEMA},
        }

    def test_training_prediction_replays_same_final_runtime_stack(self):
        row = {
            "phase": "FINAL", "home": "H", "away": "A",
            "structural_home_runs": 4.5, "structural_away_runs": 4.2,
            "features": {},
            "options": [
                {"market": "ML", "name": "H", "p_market": None, "sharp_weight": 0.0},
                {"market": "ML", "name": "A", "p_market": None, "sharp_weight": 0.0},
            ],
        }
        model = {"active": False, "phase_models": {}}
        bootstrap = self._active_native_bootstrap()
        with patch.object(m._bootstrap, "load_model", return_value=bootstrap):
            stack = m.compose_runtime(4.5, 4.2, row, model, "FINAL")
            pred = pro_model.predict_market_triplet(row, "ML", model)
        expected = engine.prob_home_win(stack["home_mu"], stack["away_mu"], stack["dispersion"], stack["environment_sigma"])
        self.assertAlmostEqual(pred["conditional"], expected, places=9)
        self.assertTrue(stack["bootstrap_run"]["active"])

    def test_sharp_only_lines_never_become_canonical_training_lines(self):
        row = {"home": "H", "away": "A", "options": [
            {"market": "RUNLINE", "name": "H", "point": -1.5, "is_canonical_line": False,
             "line_source": "sharp", "winamax_eval": {"price": None}},
            {"market": "RUNLINE", "name": "A", "point": 1.5, "is_canonical_line": False,
             "line_source": "sharp", "winamax_eval": {"price": None}},
            {"market": "TOTAL", "name": "Over", "point": 8.5, "is_canonical_line": False,
             "line_source": "sharp", "winamax_eval": {"price": None}},
            {"market": "TOTAL", "name": "Under", "point": 8.5, "is_canonical_line": False,
             "line_source": "sharp", "winamax_eval": {"price": None}},
        ]}
        self.assertEqual(pro_model.canonical_market_pair(row, "RUNLINE"), (None, None))
        self.assertEqual(pro_model.canonical_market_pair(row, "TOTAL"), (None, None))

    def test_stale_or_unpriced_canonical_line_is_excluded_from_training(self):
        row = {"home": "H", "away": "A", "options": [
            {"market": "TOTAL", "name": "Over", "point": 8.5, "is_canonical_line": True,
             "line_source": "winamax", "winamax_eval": {"price": None}},
            {"market": "TOTAL", "name": "Under", "point": 8.5, "is_canonical_line": True,
             "line_source": "winamax", "winamax_eval": {"price": None}},
        ]}
        self.assertEqual(pro_model.canonical_market_pair(row, "TOTAL"), (None, None))

    def test_legacy_1801_style_rows_are_incompatible_with_v123_baseline(self):
        rows = [{"game_pk": i, "game_date": f"2026-04-{i:02d}T00:00:00Z", "home_score": 4, "away_score": 3,
                 "v10": {"home_struct": 4.2, "away_struct": 4.0}} for i in range(1, 7)]
        model = hb.build_model(rows, min_games=5, fingerprint="legacy")
        self.assertEqual(model["status"], "INCOMPATIBLE_BASELINE")
        self.assertFalse(model["eligible_for_final_prior"])
        self.assertEqual(model["metadata"]["native_baseline_games"], 0)

    def test_frozen_test_is_reporting_only_not_activation_gate(self):
        rows = []
        for i in range(12):
            rows.append({
                "game_pk": i, "game_date": f"2026-05-{i+1:02d}T00:00:00Z", "home_score": 5, "away_score": 3,
                "v12_3": {"baseline_schema": hb.BASELINE_SCHEMA, "home_struct": 4.5, "away_struct": 3.5},
            })
        positive = {"team_rmse_gain": .02, "total_rmse_gain": .02, "base": {}, "candidate": {}}
        negative_test = {"team_rmse_gain": -.50, "total_rmse_gain": -.50, "base": {}, "candidate": {}}
        inactive_dist = ({"active": False, "value": config.RUN_DISPERSION}, {"active": False, "sigma": config.RUN_ENV_SIGMA})
        with patch.object(hb.legacy, "_correction_eval", side_effect=[positive, negative_test]), \
             patch.object(hb.legacy, "_walk_forward_gate", return_value={"passes": True, "status": "PASS", "windows": []}), \
             patch.object(hb, "_distribution_components", return_value=inactive_dist):
            model = hb.build_model(rows, min_games=9, fingerprint="native")
        self.assertTrue(model["run_correction"]["active"])
        self.assertLess(model["run_correction"]["test"]["team_rmse_gain"], 0)
        self.assertFalse(model["metadata"]["test_used_for_activation"])

    def test_bootstrap_artifact_invalidates_algorithm_or_config_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)/"data.jsonl"
            model_path = Path(td)/"model.json"
            row = {"game_pk": 1, "game_date": "2026-05-01T00:00:00Z", "home_score": 4, "away_score": 3}
            data.write_text(json.dumps(row)+"\n", encoding="utf-8")
            bad = hb.build_model([row], min_games=9, fingerprint=hb.source_fingerprint(data))
            bad["metadata"]["algorithm_fingerprint"] = "obsolete"
            hb.write_model(bad, model_path)
            rebuilt = hb.ensure_artifact(data, model_path)
            self.assertEqual(rebuilt["metadata"]["algorithm_fingerprint"], hb.algorithm_fingerprint())
            self.assertEqual(rebuilt["metadata"]["config_fingerprint"], hb.config_fingerprint())

    def test_live_validated_requires_quality_not_only_sample_size(self):
        summary = {
            "settled_singles": config.MIN_PROD_SETTLED_BETS, "settled_combos": 0,
            "close_candidate_clv_n": config.MIN_PROD_CLV_OBSERVATIONS,
            "mean_close_candidate_clv_pct": -.01, "positive_close_candidate_clv_rate": .40,
            "roi": .20,
        }
        gate = pro_model.production_evidence_gate(summary)
        self.assertFalse(gate["passes"])
        self.assertFalse(gate["clv_safe"])
        self.assertNotEqual(gate["status"], "VALIDATED")

    def test_selector_score_is_favorite_underdog_neutral_at_equal_ev(self):
        dq = {"score": .82}
        ev = .08
        unc = .03
        fav = {"price": 1.50, "p_win": (1+ev)/1.50, "p_push": 0, "ev_at_price": ev, "uncertainty": unc}
        dog = {"price": 3.00, "p_win": (1+ev)/3.00, "p_push": 0, "ev_at_price": ev, "uncertainty": unc}
        sf = selector._score({}, fav, dq)
        sd = selector._score({}, dog, dq)
        self.assertAlmostEqual(sf, sd, places=8)

    def test_paid_odds_workflows_are_non_publishing_and_manual_only(self):
        research = Path(".github/workflows/v12-3-research-collector.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", research)
        self.assertNotIn("schedule:", research)
        self.assertIn("V123_RESEARCH_ONLY: '1'", research)
        self.assertIn("Assert no research recommendation was created", research)
        self.assertNotIn("--send-persisted", research)

        text = Path(".github/workflows/market-snapshot.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("ODDS_API_KEY", text)

    def test_closing_window_covers_15_minute_snapshot_cadence(self):
        self.assertGreaterEqual(config.CLOSING_CANDIDATE_WINDOW_MIN, 20)


if __name__ == "__main__":
    unittest.main()
