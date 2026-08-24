from __future__ import annotations

import unittest

from v14 import run_model


class V14NativeRunModelTests(unittest.TestCase):
    def _feature(self, *, attested=True, as_of="2026-08-20T20:00:00Z"):
        provenance = {}
        for name in ("team_stats", "lineup", "starter_stats"):
            provenance[name] = {
                "source": "recorded-test-source",
                "timestamp_basis": "recorded_http_replay_capture",
                "source_timestamp_attested": attested,
                "point_in_time": True,
                "postgame_identity": False,
                "observed_at": as_of,
            }
        return {
            "schema": run_model.SOURCE_FEATURE_SCHEMA,
            "feature_contract": run_model.SOURCE_FEATURE_CONTRACT,
            "game_pk": 1,
            "game_date": "2026-08-20T23:00:00Z",
            "as_of": as_of,
            "phase": "FINAL",
            "point_in_time": True,
            "model_generation": "transport-generation-does-not-define-v14",
            "feature_provenance": provenance,
            "context": {
                "home_starter": {"era": 3.50, "whip": 1.15},
                "away_starter": {"era": 4.20, "whip": 1.30},
            },
            "features": {
                "home_ops": .760,
                "away_ops": .710,
                "home_lineup_ops": .780,
                "away_lineup_ops": .700,
                "home_team_era": 3.80,
                "away_team_era": 4.30,
                "park_factor": 1.04,
                "park_factor_runtime": {"leakage_safe": True},
                # Deliberately present legacy/V13 values that V14 must ignore.
                "home_mu": 12.0,
                "away_mu": .5,
                "learned_run_adjustment": {"home_delta": 5.0, "away_delta": -5.0},
            },
        }

    def _label(self):
        return {
            "schema": run_model.SOURCE_LABEL_SCHEMA,
            "game_pk": 1,
            "game_date": "2026-08-20T23:00:00Z",
            "settled_at": "2026-08-21T03:00:00Z",
            "home_score": 6,
            "away_score": 3,
        }

    def test_model_is_deliberately_small(self):
        self.assertEqual(run_model.FEATURE_NAMES, (
            "home_indicator", "offense_ops", "lineup_ops", "opponent_team_era",
            "opponent_starter_era", "opponent_starter_whip", "park_factor",
        ))
        self.assertEqual(run_model.MIN_NATIVE_GAMES, 300)
        self.assertNotIn("market", " ".join(run_model.FEATURE_NAMES).lower())
        self.assertNotIn("weather", " ".join(run_model.FEATURE_NAMES).lower())
        self.assertNotIn("bullpen", " ".join(run_model.FEATURE_NAMES).lower())

    def test_native_training_requires_attested_pit_sources(self):
        games, report = run_model.native_games([self._feature(attested=False)], [self._label()])
        self.assertEqual(games, [])
        self.assertEqual(report["feature_rejections"]["source_timestamp_not_promotion_grade"], 1)

    def test_label_is_joined_separately_after_game(self):
        games, report = run_model.native_games([self._feature()], [self._label()])
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["home_runs"], 6)
        self.assertEqual(games[0]["away_runs"], 3)
        self.assertEqual(report["joined_native_games"], 1)
        self.assertNotIn("home_score", self._feature())

    def test_v13_engineered_run_deltas_do_not_change_v14_features(self):
        row = self._feature()
        before_home = run_model._side_features(row, True)
        before_away = run_model._side_features(row, False)
        row["features"]["home_mu"] = 1.0
        row["features"]["away_mu"] = 15.0
        row["features"]["learned_run_adjustment"] = {"home_delta": -9.0, "away_delta": 9.0}
        self.assertEqual(before_home, run_model._side_features(row, True))
        self.assertEqual(before_away, run_model._side_features(row, False))

    def test_below_real_volume_floor_stays_collecting(self):
        artifact = run_model.build([self._feature()], [self._label()])
        self.assertFalse(artifact["active_for_shadow"])
        self.assertEqual(artifact["status"], "COLLECTING_NATIVE_PIT")
        self.assertEqual(artifact["native_games"], 1)
        self.assertEqual(artifact["games_needed"], run_model.MIN_NATIVE_GAMES - 1)
        self.assertFalse(artifact["market_probability_used"])

    def test_poisson_ridge_learns_simple_offense_signal(self):
        xs, ys = [], []
        for i in range(120):
            high = i % 2 == 0
            offense = .90 if high else .60
            lineup = .88 if high else .62
            xs.append([float(i % 3 == 0), offense, lineup, 4.0, 4.0, 1.25, 1.0])
            ys.append(6 if high else 2)
        model = run_model._fit_poisson(xs, ys, ridge=.1)
        low = run_model._predict(model, [0.0, .60, .62, 4.0, 4.0, 1.25, 1.0])
        high = run_model._predict(model, [0.0, .90, .88, 4.0, 4.0, 1.25, 1.0])
        self.assertGreater(high, low)
        self.assertGreater(high - low, 1.0)

    def test_predict_pair_requires_validated_shadow_artifact(self):
        xs = [
            [0.0, .60, .62, 4.0, 4.0, 1.25, 1.0],
            [1.0, .90, .88, 4.0, 4.0, 1.25, 1.0],
        ] * 40
        ys = [2, 6] * 40
        model = run_model._fit_poisson(xs, ys, ridge=.1)
        inactive = {"schema": run_model.SCHEMA, "active_for_shadow": False, "model": model}
        self.assertIsNone(run_model.predict_pair(self._feature(), inactive))
        active = {"schema": run_model.SCHEMA, "active_for_shadow": True, "model": model}
        pair = run_model.predict_pair(self._feature(), active)
        self.assertIsNotNone(pair)
        self.assertTrue(all(run_model.MIN_MU <= p <= run_model.MAX_MU for p in pair))


if __name__ == "__main__":
    unittest.main()
