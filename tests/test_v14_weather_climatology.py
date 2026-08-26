from __future__ import annotations

import unittest

from v14.weather_climatology import fetch


class WeatherClimatologyTests(unittest.TestCase):
    def test_builds_monthly_density_and_wind_out_baseline(self):
        calls=[]
        def getter(url,params):
            calls.append((url,dict(params)))
            return {"properties":{"parameter":{
                "T2M":{"AUG":25.0},
                "RH2M":{"AUG":50.0},
                "PS":{"AUG":100.0},
                "WS10M":{"AUG":4.0},
                "WD10M":{"AUG":180.0},
            }}}
        out=fetch(34.0,-118.0,month=8,outfield_bearing_deg=0.0,getter=getter)
        self.assertEqual(out["status"],"READY_SHADOW")
        self.assertGreater(out["venue_baseline_density_kg_m3"],1.0)
        self.assertLess(out["venue_baseline_density_kg_m3"],1.4)
        self.assertAlmostEqual(out["surface_pressure_hpa"],1000.0)
        self.assertGreater(out["venue_baseline_wind_out_mph"],0.0)
        self.assertEqual(calls[0][1]["parameters"],"T2M,RH2M,PS,WS10M,WD10M")
        self.assertFalse(out["champion_impact"])

    def test_missing_parameter_fails_closed(self):
        def getter(url,params):
            return {"properties":{"parameter":{"T2M":{"JUL":20},"RH2M":{"JUL":40}}}}
        out=fetch(40,-75,month=7,outfield_bearing_deg=30,getter=getter)
        self.assertEqual(out["status"],"COLLECTING")
        self.assertIn("PS",out["missing"])

    def test_invalid_geometry_is_not_imputed(self):
        out=fetch(40,-75,month=7,outfield_bearing_deg=400,getter=lambda *_:{})
        self.assertEqual(out["status"],"COLLECTING")
        self.assertNotIn("venue_baseline_density_kg_m3",out)


if __name__=="__main__":
    unittest.main()
