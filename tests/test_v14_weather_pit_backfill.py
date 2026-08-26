from __future__ import annotations

import unittest

from v14.weather_pit_backfill import build, build_row


FEATURE={"game_pk":"1","game_date":"2026-04-10T20:00:00+00:00","as_of":"2026-04-10T18:00:00+00:00","home":"Chicago Cubs"}


def fake_weather(url:str,params:dict):
    return {"hourly":{"time":["2026-04-10T20:00:00+00:00"],"temperature_2m":[18.0],"relative_humidity_2m":[55.0],"dew_point_2m":[9.0],"surface_pressure":[1008.0],"precipitation":[0.0],"cloud_cover":[30.0],"wind_speed_10m":[14.0],"wind_direction_10m":[220.0],"wind_gusts_10m":[22.0]}}


class WeatherPitBackfillTests(unittest.TestCase):
    def test_forecast_run_is_pregame_and_point_in_time(self):
        row=build_row(FEATURE,fetch_json=fake_weather)
        weather=row["weather"]
        self.assertTrue(weather["available"])
        self.assertTrue(weather["point_in_time"])
        self.assertLess(weather["forecast_run"],row["game_date"])
        self.assertEqual(weather["temperature_c"],18.0)
        self.assertFalse(row["auto_activation"])

    def test_postgame_asof_fails_closed(self):
        bad={**FEATURE,"as_of":"2026-04-10T21:00:00+00:00"}
        with self.assertRaises(ValueError):build_row(bad,fetch_json=fake_weather)

    def test_backfill_reports_coverage_without_imputation(self):
        out=build([FEATURE],fetch_json=fake_weather)
        self.assertEqual(out["coverage"]["pit_rows"],1)
        self.assertEqual(out["coverage"]["available_weather"],1)
        self.assertTrue(out["point_in_time"])
        self.assertFalse(out["auto_activation"])


if __name__=="__main__":unittest.main()
