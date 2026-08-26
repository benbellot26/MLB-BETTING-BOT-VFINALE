from __future__ import annotations

import unittest

from v14.weather_live_shadow import fetch, merge_environment


class WeatherLiveShadowTests(unittest.TestCase):
    def forecast_getter(self,url,params):
        return {"hourly":{"time":["2026-08-27T19:00","2026-08-27T20:00","2026-08-27T21:00"],"temperature_2m":[80,81,79],"relative_humidity_2m":[45,46,50],"surface_pressure":[1002,1001,1000],"wind_speed_10m":[8,9,7],"wind_direction_10m":[180,190,200]}}

    def test_complete_forecast_is_strict_shadow(self):
        out=fetch(40.0,-75.0,game_date="2026-08-27T20:15:00Z",analyzed_at="2026-08-27T16:00:00Z",getter=self.forecast_getter)
        self.assertEqual(out["status"],"READY_SHADOW");self.assertEqual(out["temperature_f"],81);self.assertEqual(out["humidity_pct"],46);self.assertEqual(out["pressure_hpa"],1001);self.assertEqual(out["wind_direction_deg"],190);self.assertIsNone(out["outfield_bearing_deg"]);self.assertFalse(out["champion_impact"]);self.assertFalse(out["auto_activation"])

    def test_reference_enrichment_supplies_bearing_and_venue_month_baseline(self):
        calls=[]
        def reference_getter(url,params):
            calls.append((url,dict(params)))
            if "statsapi.mlb.com" in url:
                return {"venues":[{"id":2681,"name":"Citizens Bank Park","location":{"azimuthAngle":9,"defaultCoordinates":{"latitude":40.0,"longitude":-75.0}}}]}
            if "power.larc.nasa.gov" in url:
                return {"properties":{"parameter":{
                    "T2M":{"AUG":25.0},"RH2M":{"AUG":50.0},"PS":{"AUG":100.0},"WS10M":{"AUG":4.0},"WD10M":{"AUG":180.0}
                }}}
            raise AssertionError(url)
        out=fetch(40.0,-75.0,game_date="2026-08-27T20:15:00Z",analyzed_at="2026-08-27T16:00:00Z",getter=self.forecast_getter,reference_getter=reference_getter)
        self.assertEqual(out["outfield_bearing_deg"],9.0)
        self.assertEqual(out["venue_geometry"]["venue_name"],"Citizens Bank Park")
        self.assertEqual(out["weather_climatology"]["status"],"READY_SHADOW")
        self.assertIsNotNone(out["venue_baseline_density_kg_m3"])
        self.assertIsNotNone(out["venue_baseline_wind_out_mph"])
        env=merge_environment({"roof":"Open"},out)
        self.assertEqual(env["outfield_bearing_deg"],9.0)
        self.assertIsNotNone(env["venue_baseline_density_kg_m3"])
        self.assertEqual(env["venue_geometry_shadow"]["venue_id"],"2681")
        self.assertTrue(any("statsapi.mlb.com" in url for url,_ in calls))
        self.assertTrue(any("power.larc.nasa.gov" in url for url,_ in calls))

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
