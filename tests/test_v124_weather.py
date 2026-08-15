from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import predictive_v124 as v124
from v11 import v124_weather as weather


class V124WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        weather.install()

    def result(self, home="Boston Red Sox"):
        return {
            "game_pk": 123,
            "game": {"gamePk": 123, "gameDate": "2026-08-15T23:10:00Z", "venue": {"id": 3}},
            "ctx": {"home": home, "away": "New York Yankees"},
            "features": {
                "park_factor": 1.03,
                "weather": {
                    "available": True,
                    "temperature_c": 30.0,
                    "humidity_pct": 45.0,
                    "surface_pressure_hpa": 995.0,
                    "precip_probability": 10.0,
                    "cloud_cover_pct": 20.0,
                    "wind_kph": 20.0,
                    "wind_direction_deg": 180.0,
                    "wind_gust_kph": 28.0,
                },
            },
        }

    def test_bearing_projection_out_and_in(self):
        out = weather._project_wind_by_bearing(20, 180, 0)
        inside = weather._project_wind_by_bearing(20, 0, 0)
        cross = weather._project_wind_by_bearing(20, 90, 0)
        self.assertAlmostEqual(out["out_kph"], 20.0, places=5)
        self.assertAlmostEqual(inside["out_kph"], -20.0, places=5)
        self.assertAlmostEqual(cross["out_kph"], 0.0, places=5)
        self.assertAlmostEqual(abs(cross["cross_kph"]), 20.0, places=5)

    def test_mlb_relative_wind_parser(self):
        out = weather._parse_mlb_relative_wind({"wind": "10 mph, Out To CF"})
        inside = weather._parse_mlb_relative_wind({"wind": "10 mph, In From CF"})
        lr = weather._parse_mlb_relative_wind({"wind": "12 mph, L To R"})
        self.assertGreater(out["out_kph"], 0)
        self.assertLess(inside["out_kph"], 0)
        self.assertEqual(lr["out_kph"], 0.0)
        self.assertGreater(lr["cross_kph"], 0)

    def test_air_density_responds_to_conditions(self):
        warm_low = weather._air_density_kg_m3(32, 45, 990)
        cold_high = weather._air_density_kg_m3(5, 45, 1025)
        self.assertLess(warm_low, cold_high)

    def test_retractable_unknown_fails_neutral(self):
        result = self.result("Houston Astros")
        with patch.object(weather, "_venue_metadata", return_value={"roof_type": "Retractable", "azimuth_deg": 20}), \
             patch.object(weather, "_mlb_game_weather", return_value={"available": True, "weather": {}}):
            mod = weather._weather_module(result, True)
        self.assertEqual(mod["status"], "ROOF_UNKNOWN_NEUTRAL")
        self.assertEqual(mod["home_factor"], 1.0)
        self.assertEqual(mod["away_factor"], 1.0)

    def test_fixed_dome_fails_neutral(self):
        result = self.result("Tampa Bay Rays")
        with patch.object(weather, "_venue_metadata", return_value={"roof_type": "Dome", "azimuth_deg": 20}), \
             patch.object(weather, "_mlb_game_weather", return_value={"available": True, "weather": {}}):
            mod = weather._weather_module(result, True)
        self.assertEqual(mod["status"], "ROOF_NEUTRAL")
        self.assertEqual(mod["home_factor"], 1.0)

    def test_retractable_open_uses_weather(self):
        result = self.result("Houston Astros")
        with patch.object(weather, "_venue_metadata", return_value={"roof_type": "Retractable", "azimuth_deg": 0}), \
             patch.object(weather, "_mlb_game_weather", return_value={
                 "available": True, "roof_state": "OPEN", "weather": {"wind": "12 mph, Out To CF"}
             }):
            mod = weather._weather_module(result, True)
        self.assertEqual(mod["status"], "ACTIVE")
        self.assertGreater(mod["home_factor"], 1.0)
        self.assertEqual(mod["details"]["wind"]["source"], "mlb_relative")

    def test_open_air_outward_wind_increases_factor(self):
        result = self.result()
        with patch.object(weather, "_venue_metadata", return_value={"roof_type": "Open", "azimuth_deg": 0}), \
             patch.object(weather, "_mlb_game_weather", return_value={
                 "available": True, "weather": {"wind": "15 mph, Out To CF"}
             }):
            outward = weather._weather_module(result, True)
        with patch.object(weather, "_venue_metadata", return_value={"roof_type": "Open", "azimuth_deg": 0}), \
             patch.object(weather, "_mlb_game_weather", return_value={
                 "available": True, "weather": {"wind": "15 mph, In From CF"}
             }):
            inward = weather._weather_module(result, True)
        self.assertGreater(outward["home_factor"], inward["home_factor"])
        self.assertGreater(outward["details"]["wind_signal"], 0)
        self.assertLess(inward["details"]["wind_signal"], 0)

    def test_azimuth_fallback_is_used_without_mlb_direction(self):
        result = self.result()
        with patch.object(weather, "_venue_metadata", return_value={"roof_type": "Open", "azimuth_deg": 0}), \
             patch.object(weather, "_mlb_game_weather", return_value={"available": False, "weather": {}}):
            mod = weather._weather_module(result, True)
        self.assertEqual(mod["status"], "ACTIVE")
        self.assertEqual(mod["details"]["wind"]["source"], "openmeteo_x_mlb_venue_azimuth")
        self.assertGreater(mod["details"]["wind"]["effective_out_kph"], 0)

    def test_implementation_report_marks_weather_added(self):
        report = v124.implementation_report({"weather_park": {"status": "ACTIVE"}})
        self.assertEqual(report["6_weather_park_interaction"]["status"], "ADDED")
        self.assertEqual(report["6_weather_park_interaction"]["runtime"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
