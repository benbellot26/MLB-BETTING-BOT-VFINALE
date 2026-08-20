from __future__ import annotations

import json
from pathlib import Path
import unittest

from v11 import engine_v12 as v13_distribution
from v11 import extra_innings_v13 as v13_extra
from v14.benchmark import CHAMPION_GENERATION
from v14.champion_contract import validated_extra_innings_home_probability
from v14.distribution import joint_score_matrix, probability_surface
from v14.model import RunProjection
from v14.shadow import build_shadow


class V14ChampionParityTests(unittest.TestCase):
    def _projection(self, home_mu=4.8, away_mu=4.1, total_line=8.5, dispersion=7.5, environment_sigma=.08):
        extra, _ = validated_extra_innings_home_probability()
        return RunProjection(
            game_pk="parity",
            game_date="2026-08-20T23:00:00Z",
            analyzed_at="2026-08-20T20:00:00Z",
            home="Home",
            away="Away",
            home_mu=home_mu,
            away_mu=away_mu,
            total_line=total_line,
            dispersion=dispersion,
            environment_sigma=environment_sigma,
            extra_innings_home_probability=extra,
            phase="FINAL",
            source_generation=CHAMPION_GENERATION,
        )

    def test_extra_innings_prior_is_behaviorally_identical_to_v13(self):
        v14_probability, v14_meta = validated_extra_innings_home_probability()
        v13_probability, v13_meta = v13_extra.validated_home_prior()
        self.assertAlmostEqual(v14_probability, v13_probability, places=15)
        self.assertEqual(bool(v14_meta.get("active")), bool(v13_meta.get("active")))
        self.assertEqual(int(v14_meta.get("n") or 0), int(v13_meta.get("n") or 0))

    def test_joint_score_matrix_matches_v13_champion_math(self):
        cases = ((4.8, 4.1, 7.5, .08), (3.2, 5.3, 7.5, .08), (4.4, 4.4, 6.2, .0))
        for home_mu, away_mu, dispersion, env in cases:
            with self.subTest(home_mu=home_mu, away_mu=away_mu, dispersion=dispersion, env=env):
                new, _ = joint_score_matrix(
                    home_mu,
                    away_mu,
                    dispersion=dispersion,
                    environment_sigma=env,
                )
                old = v13_distribution.joint_score_matrix(
                    home_mu,
                    away_mu,
                    dispersion=dispersion,
                    env_sigma=env,
                )
                self.assertEqual(len(new), len(old))
                gap = max(abs(new[h][a] - old[h][a]) for h in range(len(old)) for a in range(len(old[h])))
                self.assertLess(gap, 1e-14)

    def test_eight_probability_surface_matches_v13_champion_math(self):
        projection = self._projection()
        surface, _ = probability_surface(projection)
        old_joint = v13_distribution.joint_score_matrix(
            projection.home_mu,
            projection.away_mu,
            dispersion=projection.dispersion,
            env_sigma=projection.environment_sigma,
        )
        old_home_ml = v13_extra.home_win_probability(
            old_joint,
            extra_innings_home_prior=projection.extra_innings_home_probability,
        )
        hm_win, hm_push = v13_distribution.prob_cover_parts(
            projection.home_mu, projection.away_mu, "home", -1.5,
            projection.dispersion, projection.environment_sigma,
        )
        hp_win, hp_push = v13_distribution.prob_cover_parts(
            projection.home_mu, projection.away_mu, "home", 1.5,
            projection.dispersion, projection.environment_sigma,
        )
        over_win, over_push = v13_distribution.prob_total_parts(
            projection.home_mu, projection.away_mu, "over", projection.total_line,
            projection.dispersion, projection.environment_sigma,
        )
        self.assertEqual(hm_push, 0.0)
        self.assertEqual(hp_push, 0.0)
        self.assertEqual(over_push, 0.0)
        self.assertAlmostEqual(surface.home_ml, old_home_ml, places=14)
        self.assertAlmostEqual(surface.away_ml, 1.0 - old_home_ml, places=14)
        self.assertAlmostEqual(surface.home_minus_1_5, hm_win, places=14)
        self.assertAlmostEqual(surface.away_plus_1_5, 1.0 - hm_win, places=14)
        self.assertAlmostEqual(surface.home_plus_1_5, hp_win, places=14)
        self.assertAlmostEqual(surface.away_minus_1_5, 1.0 - hp_win, places=14)
        self.assertAlmostEqual(surface.over, over_win, places=14)
        self.assertAlmostEqual(surface.under, 1.0 - over_win, places=14)

    def test_real_persisted_champion_snapshots_reproduce_display_surface(self):
        path = Path("data/v11_3_live.jsonl")
        if not path.exists():
            self.skipTest("persisted champion journal not available")
        checked = 0
        worst_gap = 0.0
        worst_detail = None
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("model_generation") != CHAMPION_GENERATION:
                continue
            if str(row.get("phase") or "").upper() != "FINAL":
                continue
            try:
                shadow = build_shadow(row)
            except Exception:
                continue
            champion = (shadow.get("champion_reference") or {}).get("probabilities") or {}
            candidate = shadow.get("probabilities") or {}
            if set(champion) != set(candidate) or not champion:
                continue
            for key in champion:
                gap = abs(float(candidate[key]) - float(champion[key]))
                if gap > worst_gap:
                    worst_gap = gap
                    worst_detail = {
                        "game_pk": row.get("game_pk"),
                        "market_key": key,
                        "v14": candidate[key],
                        "v13": champion[key],
                        "home_mu": row.get("hmu"),
                        "away_mu": row.get("amu"),
                        "dispersion": (row.get("features") or {}).get("run_dispersion"),
                        "environment_sigma": (row.get("features") or {}).get("run_environment_sigma"),
                        "extra_innings_home_probability": (row.get("features") or {}).get("extra_innings_home_probability"),
                    }
            checked += 1
            if checked >= 25:
                break
        self.assertGreater(checked, 0, "no complete current-generation FINAL champion snapshot available for parity")
        self.assertLessEqual(worst_gap, 2e-6, f"worst parity detail: {worst_detail}")


if __name__ == "__main__":
    unittest.main()
