import unittest

from v14.environment_physics_challenger import (
    air_density_kg_m3,
    evaluate as environment_physics,
    wind_out_component_mph,
)
from v14.run_decomposition_challenger import build as build_run_decomposition
from v14.run_decomposition_challenger import opponent_factor
from v14.starter_usage_challenger import estimate as expected_starter_usage


class V14ResearchExtensionTests(unittest.TestCase):
    def test_starter_usage_uses_observed_starts_without_activation(self):
        out = expected_starter_usage(
            {
                "inningsPitched": 90.0,
                "gamesStarted": 15,
                "inningsPerStart": 6.0,
            }
        )
        self.assertEqual(out["role"], "CHALLENGER_ONLY")
        self.assertEqual(out["status"], "READY_SHADOW")
        self.assertFalse(out["auto_activation"])
        self.assertAlmostEqual(out["expected_innings"], 6.0, places=8)
        self.assertAlmostEqual(out["expected_bullpen_innings"], 3.0, places=8)

    def test_recent_short_leash_can_only_move_shadow_expected_ip(self):
        base = expected_starter_usage(
            {"inningsPitched": 72.0, "gamesStarted": 12, "inningsPerStart": 6.0}
        )
        short = expected_starter_usage(
            {
                "inningsPitched": 72.0,
                "gamesStarted": 12,
                "inningsPerStart": 6.0,
                "recent_starts": [
                    {"innings": 4.0, "pitches": 72},
                    {"innings": 4.2, "pitches": 74},
                    {"innings": 4.1, "pitches": 75},
                ],
            }
        )
        self.assertLess(short["expected_innings"], base["expected_innings"])
        self.assertFalse(short["auto_activation"])

    def test_air_density_and_wind_vector_are_physical_diagnostics(self):
        density = air_density_kg_m3(59.0, 50.0, 1013.25)
        self.assertGreater(density, 1.0)
        self.assertLess(density, 1.35)
        # Wind FROM south (180°) blows north, aligned with a 0° outfield bearing.
        self.assertAlmostEqual(wind_out_component_mph(10.0, 180.0, 0.0), 10.0, places=8)

    def test_environment_physics_fails_closed_when_inputs_missing(self):
        out = environment_physics({"temperature_f": 80, "wind_mph": 10})
        self.assertEqual(out["status"], "COLLECTING")
        self.assertFalse(out["auto_activation"])
        self.assertIn("humidity_pct", out["missing"])
        self.assertIn("outfield_bearing_deg", out["missing"])

    def test_environment_closed_roof_is_neutral_shadow(self):
        out = environment_physics({"roof": "Closed"})
        self.assertEqual(out["status"], "READY_SHADOW")
        self.assertTrue(out["indoor"])
        self.assertEqual(out["flight_environment_index"], 0.0)

    def test_run_decomposition_weights_starter_and_bullpen_by_innings(self):
        out = opponent_factor(
            starter_factor=0.8,
            bullpen_factor=1.2,
            defense_factor=1.0,
            expected_starter_innings=6.0,
        )
        expected = (6.0 / 9.0) * 0.8 + (3.0 / 9.0) * 1.2
        self.assertAlmostEqual(out["pitching_factor"], expected, places=12)
        self.assertAlmostEqual(out["opponent_factor"], expected, places=12)
        self.assertFalse(out["auto_activation"])

    def test_run_decomposition_never_imputes_missing_independent_components(self):
        out = build_run_decomposition(
            starter_usage={"expected_innings": 5.5},
            starter_factor=0.9,
            bullpen_factor=None,
            defense_factor=1.0,
        )
        self.assertEqual(out["status"], "COLLECTING")
        self.assertIn("bullpen_factor", out["missing"])
        self.assertFalse(out["auto_activation"])


if __name__ == "__main__":
    unittest.main()
