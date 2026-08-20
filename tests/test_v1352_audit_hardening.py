from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v11 import uncertainty_v13
from v11 import v13_daily_tracking as tracking
from v11 import v13_runtime
from v11.pipeline_v13 import ProbabilityPipelineV13


class V1352AuditHardeningTests(unittest.TestCase):
    def test_runtime_hooks_are_explicit_and_complete(self):
        v13_runtime.install()
        status=v13_runtime.assert_runtime_hooks()
        self.assertTrue(status["installed"])
        for key in ("engine_analyze","runner_row","bootstrap","analysis_points","extra_innings"):
            self.assertTrue(status[key],key)

    def test_uncertainty_is_not_claimed_as_validated_confidence_interval(self):
        band=uncertainty_v13.empirical_interval(.60,calibration_n=0,phase_n=50,market_n=50,data_quality=.9)
        self.assertEqual(band["user_facing_type"],"model_uncertainty_band")
        self.assertFalse(band["coverage_validated"])
        self.assertIsNone(band["nominal_level"])
        self.assertIsNone(band["confidence_level"])
        self.assertEqual(band["construction_target_level"],.90)

    def test_market_tracking_polls_only_t60_and_close_once(self):
        now=datetime(2026,8,18,12,0,tzinfo=timezone.utc)
        base={"game_date":(now+timedelta(minutes=60)).isoformat()}
        self.assertEqual(tracking._poll_reason_for_state(base,now),"t60")
        self.assertIsNone(tracking._poll_reason_for_state({**base,"t60_observed_at":now.isoformat()},now))
        close={"game_date":(now+timedelta(minutes=15)).isoformat()}
        self.assertEqual(tracking._poll_reason_for_state(close,now),"close")
        self.assertIsNone(tracking._poll_reason_for_state({**close,"close_observed_at":now.isoformat()},now))

    def test_validated_posterior_can_move_shadow_but_not_primary(self):
        calibration={"schema":"v13-baseball-calibration-model-v2","baseball_only":True,"calibrators":{}}
        posterior={"entries":{"PHASE:FINAL:ML":{"active_for_shadow":True,"weight":1.0,"games":100}}}
        pipe=ProbabilityPipelineV13(calibration,posterior)
        opt={"market":"ML","name":"Home","p_structural":.60,"p_market":.40,"p_push":0.0}
        v13_runtime.upgrade_option(opt,"FINAL",pipe)
        self.assertAlmostEqual(opt["p_posterior"],.40)
        self.assertAlmostEqual(opt["p_predictive_final"],.60)
        self.assertEqual(opt["posterior_weight_v13"],1.0)
        self.assertFalse(opt["posterior_allowed_for_edge"])

    def test_production_is_manual_only_and_research_version_check_is_fingerprint_based(self):
        prod=Path(".github/workflows/mlb-bot.yml").read_text(encoding="utf-8")
        research=Path(".github/workflows/v12-3-research-collector.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:",prod)
        self.assertNotIn("schedule:",prod)
        self.assertNotIn("v13_production_gate",prod)
        self.assertNotIn("needs.gate.outputs.run_needed == 'true'",prod)
        self.assertIn("V13_DISCORD_FINAL_ONLY: '0'",prod)
        self.assertIn("MODEL_GENERATION_FINGERPRINT",research)
        self.assertNotIn("startswith('13.5-')",research)
        self.assertIn("v13_research_gate",research)

    def test_shared_preflight_is_used_by_ci_production_backfill_and_research(self):
        paths=(
            ".github/workflows/ci.yml",
            ".github/workflows/mlb-bot.yml",
            ".github/workflows/v13-historical-backfill.yml",
            ".github/workflows/v12-3-research-collector.yml",
        )
        for path in paths:
            text=Path(path).read_text(encoding="utf-8")
            self.assertIn("v11.v13_preflight",text,path)


if __name__=="__main__":
    unittest.main()
