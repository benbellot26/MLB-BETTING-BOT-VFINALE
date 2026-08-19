from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from v11 import context
from v11 import v13_preflight
from v11 import v1310_deep_audit_closure as closure
from v11 import v138_monitoring


class V1310DeepAuditRegistryTests(unittest.TestCase):
    def test_registry_declares_behavioral_verification_contract(self):
        self.assertEqual(len(closure.POINTS), 35)
        substantive=[p for p in closure.POINTS if not p.get("compatibility_retained")]
        self.assertTrue(substantive)
        self.assertTrue(all(p.get("test_id") for p in substantive))
        self.assertIn("behavioral", closure.evaluate(run_behavioral_tests=False)["claim"].lower())
        self.assertIn("token presence is not accepted", closure.evaluate(run_behavioral_tests=False)["legacy_v139_registry_role"])

    def test_monitoring_exposes_provider_freshness_contract(self):
        now=datetime(2026,8,19,18,0,tzinfo=timezone.utc)
        self.assertAlmostEqual(v138_monitoring._age_hours("2026-08-19T12:00:00Z",now),6.0)
        self.assertIsNone(v138_monitoring._age_hours(None,now))
        self.assertGreater(v138_monitoring.PROVIDER_STALE_HOURS,0)
        self.assertGreaterEqual(v138_monitoring.STATCAST_STALE_HOURS,v138_monitoring.PROVIDER_STALE_HOURS)

    def test_state_writing_workflows_share_concurrency_lock(self):
        paths=(
            ".github/workflows/mlb-bot.yml",
            ".github/workflows/v13-7-free-data-collector.yml",
            ".github/workflows/v13-8-audit-closure.yml",
            ".github/workflows/v13-historical-backfill.yml",
        )
        for path in paths:
            text=Path(path).read_text(encoding="utf-8")
            self.assertIn("group: mlb-betting-bot-state",text,path)
            self.assertIn("cancel-in-progress: false",text,path)

    def test_weather_provenance_exposes_timestamp_basis(self):
        context._WEATHER_CACHE.clear()
        game={"gameDate":"2026-08-19T23:00:00Z"}
        payload={"hourly":{
            "time":["2026-08-19T23:00"],"temperature_2m":[21.0],"relative_humidity_2m":[50.0],
            "dew_point_2m":[10.0],"surface_pressure":[1000.0],"precipitation_probability":[0.0],
            "cloud_cover":[20.0],"wind_speed_10m":[8.0],"wind_direction_10m":[180.0],"wind_gusts_10m":[12.0],
        }}
        with patch.object(context.core,"replay_as_of",return_value="2026-08-19T18:00:00Z"), \
             patch.object(context.core,"http_json",return_value=payload):
            row=context.weather_for_game(game,"New York Yankees")
        self.assertTrue(row["point_in_time"])
        self.assertEqual(row["forecast_reference_at"],"2026-08-19T18:00:00+00:00")
        self.assertEqual(row["timestamp_basis"],"retrieval_time; provider issue timestamp not exposed by this endpoint")
        self.assertFalse(row["source_issue_time_available"])

    def test_deep_audit_behavior_suite_is_in_shared_preflight(self):
        self.assertIn("tests.test_v1310_deep_audit_hardening",v13_preflight.CRITICAL_TEST_MODULES)
        self.assertIn("tests.test_v1310_deep_audit_registry",v13_preflight.CRITICAL_TEST_MODULES)

    def test_discord_visual_suite_is_in_shared_preflight(self):
        self.assertIn("tests.test_v13_discord_visual",v13_preflight.CRITICAL_TEST_MODULES)

    def test_free_data_workflow_collects_park_before_team_history(self):
        text=Path(".github/workflows/v13-7-free-data-collector.yml").read_text(encoding="utf-8")
        park=text.index("python -m v11.v137_park_factors")
        team=text.index("python -m v11.v137_team_history")
        self.assertLess(park,team)
        self.assertIn("rolling=3",text)


if __name__ == "__main__":
    unittest.main()
