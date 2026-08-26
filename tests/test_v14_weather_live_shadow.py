from __future__ import annotations

import unittest

from v14.weather_live_shadow import fetch, merge_environment


class WeatherLiveShadowTests(unittest.TestCase):
    def test_complete_forecast_is_strict_shadow(self):
        def getter(url,params):
            return {"hourly":{"time":["2026-08-27T19:00","2026-08-27T20:00","2026-08-27T21:00"],"temperature_2m":[80,81,79],"relative_humidity_2m":[45,46,50],"surface_pressure":[1002,1001,1000],"wind_speed_10m":[8,9,7],"wind_direction_10m":[180,190,200]}}
        out=fetch(40.0,-75.0,game_date="2026-08-27T20:15:00Z",analyzed_at="2026-08-27T16:00:00Z",getter=getter)
        self.assertEqual(out["status"],"READY_SHADOW");self.assertEqual(out["temperature_f"],81);self.assertEqual(out["humidity_pct"],46);self.assertEqual(out["pressure_hpa"],1001);self.assertEqual(out["wind_direction_deg"],190);self.assertIsNone(out["outfield_bearing_deg"]);self.assertFalse(out["champion_impact"]);self.assertFalse(out["auto_activation"])

    def test_postgame_request_fails_closed_without_fetch(self):
        called=[]
        def getter(url,params):called.append(True);return {}
        out=fetch(40,-75,game_date="2026-08-27T20:00:00Z",analyzed_at="2026-08-27T20:00:00Z",getter=getter)
        self.assertEqual(out["status"],"COLLECTING");self.assertFalse(called)

    def test_merge_preserves_mlb_roof_and_adds_physical_fields(self):
        weather={"status":"READY_SHADOW","temperature_f":82.0,"humidity_pct":55.0,"pressure_hpa":998.0,"wind_mph":11.0,"wind_direction_deg":225.0,"source":"Open-Meteo generic forecast API","forecast_valid_time":"2026-08-27T20:00:00+00:00"}
        out=merge_environment({"roof":"Open","condition":"Clear","temperature_f":80},weather)
        self.assertEqual(out["roof"],"Open");self.assertEqual(out["condition"],"Clear");self.assertEqual(out["temperature_f"],82);self.assertEqual(out["humidity_pct"],55);self.assertTrue(out["weather_shadow_point_in_time"])

    def test_missing_variable_does_not_impute(self):
        def getter(url,params):return {"hourly":{"time":["2026-08-27T20:00"],"temperature_2m":[80],"relative_humidity_2m":[50],"surface_pressure":[1000],"wind_speed_10m":[8],"wind_direction_10m":[None]}}
        out=fetch(40,-75,game_date="2026-08-27T20:00:00Z",analyzed_at="2026-08-27T16:00:00Z",getter=getter);self.assertEqual(out["status"],"COLLECTING");self.assertIn("wind_direction_deg",out["missing"])


if __name__=="__main__":unittest.main()
