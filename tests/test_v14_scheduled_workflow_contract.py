from pathlib import Path
import unittest


WORKFLOW=Path(".github/workflows/mlb-bot.yml")


class V14ScheduledWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")

    def test_schedule_wakes_frequently_but_gate_precedes_paid_odds(self):
        self.assertIn("- cron: '*/10 * * * *'",self.text)
        gate=self.text.index("- name: Resolve manual or objective scheduled FINAL gate")
        quota=self.text.index("- name: Refresh provider quota with zero-credit endpoint")
        reserve=self.text.index("- name: Reserve and persist every paid Odds snapshot before request")
        paid=self.text.index("- name: Build native Pulsar V14 production payload")
        self.assertLess(gate,quota);self.assertLess(quota,reserve);self.assertLess(reserve,paid)
        gate_block=self.text[gate:quota]
        quota_block=self.text[quota:reserve]
        reserve_block=self.text[reserve:paid]
        self.assertIn("python -m v14.scheduled_prediction_gate",gate_block)
        self.assertNotIn("ODDS_API_KEY",gate_block)
        self.assertIn("python -m v14.odds_quota_probe",quota_block)
        self.assertIn("ODDS_API_KEY",quota_block)
        self.assertNotIn("production_runtime",quota_block)
        self.assertIn("python -m v14.api_budget record-prediction",reserve_block)
        self.assertIn("python -m v14.api_budget record-manual",reserve_block)
        self.assertNotIn("ODDS_API_KEY",reserve_block)

    def test_every_paid_production_run_is_reserved_before_request(self):
        start=self.text.index("- name: Reserve and persist every paid Odds snapshot before request")
        end=self.text.index("- name: Build native Pulsar V14 production payload")
        block=self.text[start:end]
        self.assertIn("SCHEDULED_FINAL",block)
        self.assertIn("record-prediction",block)
        self.assertIn("record-manual",block)
        self.assertIn('--slate-date "$TARGET_DATE"',block)
        self.assertIn("V14_MAX_ALL_ODDS_CREDITS_PER_UTC_MONTH: '450'",block)
        self.assertIn("python -m v14.state_branch persist",block)
        self.assertIn("data: reserve V14 paid Odds request [skip ci]",block)
        self.assertNotIn("git push origin",block)

    def test_scheduled_trigger_is_stamped_into_same_production_runtime(self):
        start=self.text.index("- name: Build native Pulsar V14 production payload")
        end=self.text.index("- name: Record zero-API slate coverage",start)
        block=self.text[start:end]
        self.assertIn("ODDS_API_KEY",block)
        self.assertIn("--run-trigger \"${{ steps.gate.outputs.run_trigger }}\"",block)

    def test_scheduled_hidden_evidence_never_consumes_operational_bet_exposure(self):
        start=self.text.index("- name: Persist PIT predictions and decision evidence")
        end=self.text.index("- name: Close collection policy",start)
        block=self.text[start:end]
        self.assertIn('if [ "${{ steps.gate.outputs.run_trigger }}" = "MANUAL" ]; then',block)
        self.assertIn("python -m v14.bet_ledger record",block)

    def test_no_production_run_can_choose_certification_close_timing(self):
        self.assertNotIn("python -m v14.cost_aware_close_capture",self.text)
        self.assertNotIn("python -m v14.market_close_ledger hydrate-paper",self.text)
        close_policy=self.text.index("- name: Close collection policy")
        publish=self.text.index("- name: Publish Pulsar V14 Discord analytics",close_policy)
        self.assertIn("dedicated v14-close-capture.yml only",self.text[close_policy:publish])
        self.assertIn("steps.gate.outputs.run_trigger == 'MANUAL'",self.text[publish:])

    def test_gate_does_not_read_its_own_step_outputs(self):
        start=self.text.index("- name: Resolve manual or objective scheduled FINAL gate")
        end=self.text.index("- name: Explain scheduled no-op",start)
        self.assertNotIn("steps.gate.outputs",self.text[start:end])


if __name__=="__main__":
    unittest.main()
