from __future__ import annotations

import unittest

from v14 import MODEL_GENERATION
from v14.benchmark import CHAMPION_GENERATION, champion_surface
from v14.evidence import MIN_PAIRED_GAMES, build
from v14.model import ProbabilitySurface
from v14.shadow import build_shadow


class V14PairedEvidenceTests(unittest.TestCase):
    def _champion_result(self, analyzed_at="2026-08-20T20:00:00Z"):
        return {
            "game_pk": 101,
            "game": {"gameDate": "2026-08-20T23:00:00Z"},
            "analyzed_at": analyzed_at,
            "phase": "FINAL",
            "model_generation": CHAMPION_GENERATION,
            "ctx": {"home": "Home", "away": "Away"},
            "hmu": 4.8,
            "amu": 4.0,
            "options": [
                {"market": "ML", "name": "Home", "p_predictive_final": .60},
                {"market": "ML", "name": "Away", "p_predictive_final": .40},
                {"market": "RUNLINE", "name": "Home", "point": -1.5, "p_predictive_final": .38},
                {"market": "RUNLINE", "name": "Away", "point": 1.5, "p_predictive_final": .62},
                {"market": "RUNLINE", "name": "Home", "point": 1.5, "p_predictive_final": .76},
                {"market": "RUNLINE", "name": "Away", "point": -1.5, "p_predictive_final": .24},
                {"market": "TOTAL", "name": "Over", "point": 8.5, "is_canonical_line": True, "p_predictive_final": .54},
                {"market": "TOTAL", "name": "Under", "point": 8.5, "is_canonical_line": True, "p_predictive_final": .46},
            ],
        }

    def _label(self, game_pk=101, settled_at="2026-08-21T03:00:00Z"):
        return {
            "schema": "v13-label-store-v1",
            "game_pk": game_pk,
            "game_date": "2026-08-20T23:00:00Z",
            "settled_at": settled_at,
            "home_score": 6,
            "away_score": 3,
        }

    def test_frozen_champion_surface_extracts_exact_eight_probabilities(self):
        surface = champion_surface(self._champion_result(), total_line=8.5)
        self.assertEqual(surface, ProbabilitySurface(
            away_ml=.40, home_ml=.60,
            away_plus_1_5=.62, away_minus_1_5=.24,
            home_plus_1_5=.76, home_minus_1_5=.38,
            over=.54, under=.46,
        ))

    def test_benchmark_is_copied_only_after_v14_probability_calculation(self):
        result = self._champion_result()
        first = build_shadow(result)
        v14_first = dict(first["probabilities"])
        result["options"][0]["p_predictive_final"] = .52
        result["options"][1]["p_predictive_final"] = .48
        result["options"][2]["p_predictive_final"] = .30
        result["options"][3]["p_predictive_final"] = .70
        result["options"][4]["p_predictive_final"] = .68
        result["options"][5]["p_predictive_final"] = .32
        result["options"][6]["p_predictive_final"] = .49
        result["options"][7]["p_predictive_final"] = .51
        second = build_shadow(result)
        self.assertEqual(v14_first, second["probabilities"])
        self.assertNotEqual(first["champion_reference"]["probabilities"], second["champion_reference"]["probabilities"])
        self.assertFalse(second["champion_reference"]["used_as_v14_model_input"])

    def test_latest_final_snapshot_counts_one_unique_game(self):
        early_final = build_shadow(self._champion_result("2026-08-20T19:00:00Z"))
        late_final = build_shadow(self._champion_result("2026-08-20T22:00:00Z"))
        report = build([early_final, late_final], [self._label()])
        self.assertEqual(report["paired_games"], 1)
        self.assertEqual(report["game_ids"], ["101"])
        for market in ("ML", "RUNLINE", "TOTAL", "OVERALL"):
            self.assertEqual(report["markets"][market]["n_games"], 1)

    def test_runline_pair_is_averaged_inside_game_not_counted_as_two_games(self):
        shadow = build_shadow(self._champion_result())
        report = build([shadow], [self._label()])
        self.assertEqual(report["markets"]["RUNLINE"]["n_games"], 1)
        self.assertEqual(report["sample_policy"]["unit"], "one unique MLB game")
        self.assertIn("averaged inside each game", report["sample_policy"]["runline"])

    def test_non_champion_generation_cannot_become_paired_evidence(self):
        result = self._champion_result()
        result["model_generation"] = "some-other-generation"
        shadow = build_shadow(result)
        self.assertEqual(shadow["model_generation"], MODEL_GENERATION)
        self.assertEqual(shadow["champion_reference"]["role"], "UNAVAILABLE_NON_CHAMPION_GENERATION")
        report = build([shadow], [self._label()])
        self.assertEqual(report["paired_games"], 0)
        self.assertEqual(report["shadow_rejections"]["champion_reference_missing"], 1)

    def test_label_must_be_separate_and_attested_after_game_start(self):
        shadow = build_shadow(self._champion_result())
        bad_label = self._label(settled_at="2026-08-20T22:00:00Z")
        report = build([shadow], [bad_label])
        self.assertEqual(report["paired_games"], 0)
        self.assertEqual(report["label_rejections"]["label_not_postgame_attested"], 1)

    def test_paired_evidence_cannot_promote_v14_foundation(self):
        shadow = build_shadow(self._champion_result())
        report = build([shadow], [self._label()])
        self.assertFalse(report["promotion_allowed"])
        self.assertIn("INDEPENDENT_V14_RUN_MODEL_NOT_IMPLEMENTED", report["promotion_blockers"])
        self.assertIn("V14_CALIBRATION_NOT_INDEPENDENTLY_VALIDATED", report["promotion_blockers"])
        self.assertIn(f"PAIRED_GAMES_1_OF_{MIN_PAIRED_GAMES}", report["promotion_blockers"])


if __name__ == "__main__":
    unittest.main()
