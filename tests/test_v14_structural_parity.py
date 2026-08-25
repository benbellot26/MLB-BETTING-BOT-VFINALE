from __future__ import annotations

import types
import unittest

from v11 import methodology_v123 as legacy_v123
from v14.structural import (
    LeagueBaselines,
    Starter,
    StructuralInputs,
    TeamInputs,
    enhance_starter,
    historical_pitcher_prior,
    legacy_structural_projection,
    operational_adjustments,
    project,
    rescale_for_enhanced_starters,
)


class V14StructuralParityTests(unittest.TestCase):
    def _inputs(self):
        league = LeagueBaselines(rpg=4.45, ops=.710, era=4.35, whip=1.32)
        home = TeamInputs(
            runs_per_game=4.90,
            ops=.755,
            lineup_ops=.775,
            team_era=3.85,
            starter=Starter(era=4.00, whip=1.27),
            enhanced_starter=Starter(era=3.72, whip=1.19),
            operational={
                "travel_km": 400.0,
                "timezone_shift_hours_approx": 0.5,
                "previous_extra_innings": False,
                "previous_doubleheader": False,
                "rest_days": 1,
                "bullpen_previous_game": {"relief_pitches": 52, "heavy_relievers": 1},
            },
        )
        away = TeamInputs(
            runs_per_game=4.15,
            ops=.695,
            lineup_ops=.705,
            team_era=4.55,
            starter=Starter(era=4.70, whip=1.41),
            enhanced_starter=Starter(era=4.42, whip=1.34),
            operational={
                "travel_km": 3200.0,
                "timezone_shift_hours_approx": 2.5,
                "previous_extra_innings": True,
                "previous_doubleheader": False,
                "rest_days": 0,
                "bullpen_previous_game": {"relief_pitches": 95, "heavy_relievers": 2},
            },
        )
        return StructuralInputs(league=league, home=home, away=away, static_park_factor=1.03)

    def test_operational_adjustment_matches_v13_rule_order(self):
        inputs = self._inputs()
        home_adj, away_adj = operational_adjustments(inputs)
        # Home: +.006 rest + opponent bullpen min(.035, .00022*95+.006*2)=.0329
        self.assertAlmostEqual(home_adj, .0389, places=12)
        # Away fatigue = -.012-.008-.008-.010 = -.038; home bullpen=.01744 => -.02056
        self.assertAlmostEqual(away_adj, -.02056, places=12)

    def test_current_doubleheader_penalty_is_after_clamp(self):
        base = self._inputs()
        inputs = StructuralInputs(
            league=base.league, home=base.home, away=base.away,
            static_park_factor=base.static_park_factor, current_doubleheader=True,
        )
        h0, a0 = operational_adjustments(base)
        h1, a1 = operational_adjustments(inputs)
        self.assertAlmostEqual(h1, h0 - .004, places=15)
        self.assertAlmostEqual(a1, a0 - .004, places=15)

    def test_v12_3_enhanced_starter_rescale_matches_legacy_reference(self):
        inputs = self._inputs()
        fake_core = types.SimpleNamespace(league_baselines=lambda: {
            "rpg": inputs.league.rpg,
            "ops": inputs.league.ops,
            "era": inputs.league.era,
            "whip": inputs.league.whip,
        })
        previous_core = legacy_v123._core
        legacy_v123._core = fake_core
        try:
            old_ctx = {
                "home_starter": {"era": inputs.home.starter.era, "whip": inputs.home.starter.whip},
                "away_starter": {"era": inputs.away.starter.era, "whip": inputs.away.starter.whip},
            }
            enhanced_home = {"era": inputs.home.enhanced_starter.era, "whip": inputs.home.enhanced_starter.whip}
            enhanced_away = {"era": inputs.away.enhanced_starter.era, "whip": inputs.away.enhanced_starter.whip}
            legacy_home, legacy_away, legacy_meta = legacy_v123._rescale_structural_for_v123_starters(
                4.72, 4.18, old_ctx, enhanced_home, enhanced_away,
                {"era": inputs.home.team_era}, {"era": inputs.away.team_era},
            )
        finally:
            legacy_v123._core = previous_core
        new = rescale_for_enhanced_starters(4.72, 4.18, inputs)
        self.assertAlmostEqual(new["home_mu"], legacy_home, places=15)
        self.assertAlmostEqual(new["away_mu"], legacy_away, places=15)
        for key in (
            "home_old_opponent_factor", "home_new_opponent_factor",
            "away_old_opponent_factor", "away_new_opponent_factor",
        ):
            self.assertAlmostEqual(new[key], legacy_meta[key], places=15)

    def test_pitcher_prior_uses_v13_65_35_ip_weighting(self):
        y1 = {"inningsPitched": 160, "era": 3.60, "whip": 1.18,
              "strikeoutsPer9Inn": 9.5, "walksPer9Inn": 2.5, "homeRunsPer9": 1.0}
        y2 = {"inningsPitched": 50, "era": 4.40, "whip": 1.38,
              "strikeoutsPer9Inn": 8.0, "walksPer9Inn": 3.5, "homeRunsPer9": 1.3}
        prior = historical_pitcher_prior([(y1, .65), (y2, .35)])
        w1, w2 = .65, .35 * .5
        expected_era = (3.60*w1 + 4.40*w2)/(w1+w2)
        self.assertAlmostEqual(prior["era"], expected_era, places=15)

    def test_starter_enhancement_uses_current_ip_shrinkage(self):
        current = {"inningsPitched": 60, "era": 3.20, "whip": 1.10,
                   "strikeoutsPer9Inn": 10.0, "walksPer9Inn": 2.0, "homeRunsPer9": .9}
        prior = {"era": 4.00, "whip": 1.30, "k9": 8.0, "bb9": 3.0, "hr9": 1.2}
        enhanced = enhance_starter(current, prior)
        self.assertAlmostEqual(enhanced.sample_weight, .5, places=15)
        self.assertAlmostEqual(enhanced.era, 3.60, places=15)
        self.assertAlmostEqual(enhanced.whip, 1.20, places=15)
        self.assertAlmostEqual(enhanced.k9, 9.0, places=15)

    def test_full_structural_projection_is_stable_and_v12_3_shaped(self):
        inputs = self._inputs()
        legacy = legacy_structural_projection(inputs)
        final = project(inputs)
        self.assertGreater(legacy["home_mu"], 1.8)
        self.assertLess(legacy["home_mu"], 7.5)
        self.assertGreater(final["home_mu"], 1.8)
        self.assertLess(final["home_mu"], 7.5)
        self.assertEqual(final["baseline_schema"], "v12.3-structural-v1")
        # Away starter improves in the enhanced model, so home scoring must fall.
        self.assertLess(final["home_mu"], legacy["home_mu"])
        # Home starter improves, so away scoring must fall.
        self.assertLess(final["away_mu"], legacy["away_mu"])


if __name__ == "__main__":
    unittest.main()
