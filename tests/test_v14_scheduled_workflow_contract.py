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
        reserve=self.text.index("- name: Reserve and persist automated FINAL prediction budget")
        paid=self.text.index("- name: Build native Pulsar V14 production payload")
        self.assertLess(gate,reserve)
        self.assertLess(reserve,paid)
        pre_paid=self.text[gate:paid]
        self.assertIn("python -m v14.scheduled_prediction_gate",pre_paid)
        self.assertIn("python -m v14.api_budget record-prediction",pre_paid)
        self.assertNotIn("ODDS_API_KEY",pre_paid)

    def test_budget_reservation_is_persisted_before_paid_request(self):
        start=self.text.index("- name: Reserve and persist automated FINAL prediction budget")
        end=self.text.index("- name: Build native Pulsar V14 production payload")
        block=self.text[start:end]
        self.assertIn("SCHEDULED_FINAL",block)
        self.assertIn("git commit -m 'data: reserve V14 scheduled FINAL prediction request [skip ci]'",block)
        self.assertIn("git push origin",block)

    def test_scheduled_trigger_is_stamped_into_same_production_runtime(self):
        start=self.text.index("- name: Build native Pulsar V14 production payload")
        end=self.text.index("- name: Record zero-API slate coverage",start)
        block=self.text[start:end]
        self.assertIn("ODDS_API_KEY",block)
        self.assertIn("--run-trigger \"${{ steps.gate.outputs.run_trigger }}\"",block)

    def test_scheduled_hidden_evidence_never_consumes_operational_bet_exposure(self):
        start=self.text.index("- name: Persist PIT predictions and decision evidence")
        end=self.text.index("- name: Capture immediate certified close",start)
        block=self.text[start:end]
        self.assertIn('if [ "${{ steps.gate.outputs.run_trigger }}" = "MANUAL" ]; then',block)
        self.assertIn("python -m v14.bet_ledger record",block)

    def test_scheduled_entry_does_not_take_same_run_close_or_publish_discord(self):
        close_start=self.text.index("- name: Capture immediate certified close only if actually due")
        close_end=self.text.index("- name: Publish Pulsar V14 Discord analytics",close_start)
        close_block=self.text[close_start:close_end]
        self.assertIn("steps.gate.outputs.run_trigger == 'MANUAL'",close_block)
        publish=self.text[close_end:]
        self.assertIn("steps.gate.outputs.run_trigger == 'MANUAL'",publish)

    def test_gate_does_not_read_its_own_step_outputs(self):
        start=self.text.index("- name: Resolve manual or objective scheduled FINAL gate")
        end=self.text.index("- name: Explain scheduled no-op",start)
        self.assertNotIn("steps.gate.outputs",self.text[start:end])


if __name__=="__main__":
    unittest.main()
