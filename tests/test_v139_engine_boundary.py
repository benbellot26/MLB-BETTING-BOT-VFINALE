from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from v11 import v13_engine
from v11 import v139_native_context as native


class _LegacyEngine:
    __name__ = "legacy_test_engine"

    @staticmethod
    def joint_score_matrix(*args, **kwargs):
        return [[1.0]]

    def analyze(self, game, event, as_of=None):
        return {
            "game_pk": game.get("gamePk"),
            "game": game,
            "as_of": as_of,
            "ctx": {
                "home": "Home",
                "away": "Away",
                "home_id": 1,
                "away_id": 2,
                "home_starter": {"id": 10, "era": 4.0},
                "away_starter": {"id": 20, "era": 4.2},
                "home_lineup": {"players": [{"id": i, "ops": .700} for i in range(1, 10)]},
                "away_lineup": {"players": [{"id": i, "ops": .710} for i in range(11, 20)]},
            },
            "features": {"bullpen": {}},
            "options": [
                {
                    "market": "ML",
                    "name": "Home",
                    "point": None,
                    "p_baseball_raw": .61,
                    "p_baseball_calibrated": .59,
                    "p_posterior": .58,
                    "p_predictive_final": .59,
                    "p_effective": .59,
                    "p_model": .61,
                    "p_win": .59,
                    "p_push": 0.0,
                }
            ],
        }


class V139EngineBoundaryTests(unittest.TestCase):
    def test_engine_attaches_research_context_without_probability_change(self):
        legacy = _LegacyEngine()
        engine = v13_engine.V13Engine(legacy)
        with patch.object(
            native,
            "build",
            return_value={
                "schema": "v13-9-native-research-context-v2",
                "research_only": True,
                "affects_champion": False,
            },
        ):
            result = engine.analyze(
                {"gamePk": 1, "gameDate": "2026-08-19T19:00:00Z"},
                {},
                as_of="2026-08-19T17:00:00Z",
            )
        option = result["options"][0]
        self.assertEqual(option["p_baseball_calibrated"], .59)
        self.assertEqual(option["p_predictive_final"], .59)
        self.assertTrue(result["features"]["v139_native_research"]["research_only"])
        self.assertFalse(result["v13_engine"]["native_research_affects_champion"])
        self.assertEqual(engine.joint_score_matrix(), [[1.0]])

    def test_engine_fails_closed_if_research_attachment_mutates_probability(self):
        legacy = _LegacyEngine()
        engine = v13_engine.V13Engine(legacy)

        def mutate(result, as_of=None):
            result["options"][0]["p_predictive_final"] = .99
            return result

        with patch.object(native, "attach", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "mutate champion probability"):
                engine.analyze(
                    {"gamePk": 1, "gameDate": "2026-08-19T19:00:00Z"},
                    {},
                    as_of="2026-08-19T17:00:00Z",
                )

    def test_runner_engine_install_is_idempotent(self):
        runner = SimpleNamespace(engine=_LegacyEngine())
        first = v13_engine.install_runner_engine(runner)
        second = v13_engine.install_runner_engine(runner)
        self.assertIs(first, second)
        self.assertTrue(v13_engine.is_installed(runner))
        self.assertTrue(first.status()["probability_neutral_research_boundary"])

    def test_statcast_prior_rejects_artifact_generated_after_asof(self):
        report = {
            "cutoff_day": "2026-08-19",
            "stable_id_only": True,
            "unresolved_truncation": False,
            "chunks_failed": 0,
        }
        priors = {
            "generated_at": "2026-08-19T18:00:00+00:00",
            "lookback_end": "2026-08-18",
            "pitchers": {"20": {}},
            "hitters": {"1": {}},
        }
        with patch.object(native, "_load_json", return_value=report), patch.object(
            native, "_load_gzip_json", return_value=priors
        ):
            loaded, meta = native.load_statcast_priors(
                "2026-08-19T17:00:00+00:00",
                "2026-08-19T19:00:00+00:00",
            )
        self.assertEqual(loaded, {})
        self.assertFalse(meta["used"])
        self.assertEqual(meta["reason"], "statcast_prior_generated_after_asof")

    def test_statcast_prior_accepts_only_strictly_pregame_pitch_window(self):
        report = {
            "cutoff_day": "2026-08-19",
            "stable_id_only": True,
            "unresolved_truncation": False,
            "chunks_failed": 0,
        }
        priors = {
            "generated_at": "2026-08-19T12:00:00+00:00",
            "lookback_end": "2026-08-18",
            "pitchers": {"20": {}},
            "hitters": {"1": {}},
        }
        with patch.object(native, "_load_json", return_value=report), patch.object(
            native, "_load_gzip_json", return_value=priors
        ):
            loaded, meta = native.load_statcast_priors(
                "2026-08-19T17:00:00+00:00",
                "2026-08-19T19:00:00+00:00",
            )
        self.assertIs(loaded, priors)
        self.assertTrue(meta["used"])
        self.assertTrue(meta["point_in_time"])
        self.assertEqual(meta["reason"], "PIT_SAFE")

    def test_mlb_state_rejects_snapshot_observed_after_asof(self):
        state = {
            "observed_at": "2026-08-19T18:00:00+00:00",
            "snapshot_day": "2026-08-19",
            "point_in_time": True,
            "native_live": True,
            "active_rosters": {},
            "transactions": [],
        }
        with patch.object(native, "_load_gzip_json", return_value=state):
            loaded, meta = native.load_mlb_state(
                "2026-08-19T17:00:00+00:00",
                "2026-08-19T19:00:00+00:00",
            )
        self.assertEqual(loaded, {})
        self.assertFalse(meta["used"])
        self.assertEqual(meta["reason"], "mlb_state_observed_after_asof")

    def test_mlb_state_accepts_native_snapshot_already_observed(self):
        state = {
            "observed_at": "2026-08-19T12:00:00+00:00",
            "snapshot_day": "2026-08-19",
            "point_in_time": True,
            "native_live": True,
            "active_rosters": {"1": {"players": []}},
            "transactions": [],
        }
        with patch.object(native, "_load_gzip_json", return_value=state):
            loaded, meta = native.load_mlb_state(
                "2026-08-19T17:00:00+00:00",
                "2026-08-19T19:00:00+00:00",
            )
        self.assertIs(loaded, state)
        self.assertTrue(meta["used"])
        self.assertEqual(meta["reason"], "PIT_SAFE")

    def test_park_prior_requires_completed_seasons_before_game_season(self):
        artifact = {
            "seasons": {
                "2026": {
                    "ALL": {
                        "source_window_end_season": 2025,
                        "source_window_years": [2023, 2024, 2025],
                        "rows": [{"venue": "Test Park", "park_factor_index": 104}],
                    },
                    "L": {
                        "source_window_end_season": 2025,
                        "source_window_years": [2023, 2024, 2025],
                        "rows": [{"venue": "Test Park", "park_factor_index": 103}],
                    },
                    "R": {
                        "source_window_end_season": 2025,
                        "source_window_years": [2023, 2024, 2025],
                        "rows": [{"venue": "Test Park", "park_factor_index": 105}],
                    },
                }
            }
        }
        result = {"game": {"venue": {"name": "Test Park"}}}
        with patch.object(native, "_load_json", return_value=artifact):
            prior, meta = native.load_park_prior(result, "2026-08-19T19:00:00Z")
        self.assertTrue(prior["available"])
        self.assertTrue(meta["point_in_time"])
        self.assertEqual(meta["source_window_end_season"], 2025)
        self.assertEqual(meta["reason"], "COMPLETED_SEASONS_ONLY")

    def test_roster_context_is_neutral_when_pit_state_is_unavailable(self):
        ctx = {
            "home_id": 1,
            "home_lineup": {"players": [{"id": i} for i in range(1, 10)]},
        }
        out = native._roster_context({}, ctx, "home")
        self.assertFalse(out["available"])
        self.assertEqual(out["offense_factor"], 1.0)
        self.assertEqual(out["known_absent_count"], 0)

    def test_native_context_contract_never_embeds_market_or_target(self):
        result = {
            "game_pk": 1,
            "game": {
                "gameDate": "2026-08-19T19:00:00Z",
                "venue": {"name": "Test Park"},
            },
            "ctx": {
                "home_id": 1,
                "away_id": 2,
                "home_lineup": {"players": []},
                "away_lineup": {"players": []},
                "home_starter": {},
                "away_starter": {},
            },
            "features": {},
            "options": [{"p_market": .55}],
        }
        with patch.object(
            native,
            "load_statcast_priors",
            return_value=({}, {"used": False, "point_in_time": False, "reason": "test"}),
        ), patch.object(
            native,
            "load_mlb_state",
            return_value=({}, {"used": False, "point_in_time": False, "reason": "test"}),
        ), patch.object(
            native,
            "load_park_prior",
            return_value=({}, {"used": False, "point_in_time": False, "reason": "test"}),
        ):
            bundle = native.build(result, as_of="2026-08-19T17:00:00Z")
        self.assertTrue(bundle["research_only"])
        self.assertFalse(bundle["affects_champion"])
        self.assertFalse(bundle["market_data_embedded"])
        self.assertFalse(bundle["target_labels_embedded"])
        self.assertNotIn("options", bundle)


if __name__ == "__main__":
    unittest.main()
