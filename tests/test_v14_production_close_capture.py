from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/mlb-bot.yml")


class V14ProductionCloseCaptureWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_durable_prediction_persistence_precedes_immediate_close_capture(self):
        persist = self.text.index("- name: Persist PIT predictions and decision evidence")
        immediate = self.text.index("- name: Capture immediate certified close only if actually due")
        publish = self.text.index("- name: Publish Pulsar V14 Discord analytics")
        self.assertLess(persist, immediate)
        self.assertLess(immediate, publish)

    def test_immediate_capture_is_fail_soft_cost_aware_and_keeps_scheduled_fallback(self):
        start = self.text.index("- name: Capture immediate certified close only if actually due")
        end = self.text.index("- name: Publish Pulsar V14 Discord analytics")
        block = self.text[start:end]
        self.assertIn("continue-on-error: true", block)
        self.assertIn("ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}", block)
        self.assertIn("python -m v14.cost_aware_close_capture", block)
        self.assertIn("--api-usage-ledger data/v14_api_usage.jsonl", block)
        self.assertIn("python -m v14.market_close_ledger hydrate-paper", block)
        self.assertIn("python -m v14.api_budget report", block)
        self.assertIn("scheduled cost-aware close capture remains fallback", block)
        self.assertNotIn("python -m v14.market_close_ledger capture", block)
        self.assertNotIn("python -m v14.paper_ledger capture-close", block)
        self.assertNotIn("python -m v14.official_close", block)

    def test_core_persistence_does_not_depend_on_close_api(self):
        start = self.text.index("- name: Persist PIT predictions and decision evidence")
        end = self.text.index("- name: Capture immediate certified close only if actually due")
        block = self.text[start:end]
        self.assertNotIn("ODDS_API_KEY", block)
        self.assertNotIn("cost_aware_close_capture", block)
        self.assertIn("git push origin", block)

    def test_scheduled_final_gate_is_free_and_precedes_paid_prediction(self):
        self.assertIn("- cron: '*/10 * * * *'", self.text)
        gate = self.text.index("- name: Resolve manual or objective scheduled FINAL gate")
        reserve = self.text.index("- name: Reserve and persist automated FINAL prediction budget")
        paid = self.text.index("- name: Build native Pulsar V14 production payload")
        self.assertLess(gate, reserve)
        self.assertLess(reserve, paid)
        gate_block = self.text[gate:reserve]
        reserve_block = self.text[reserve:paid]
        self.assertIn("python -m v14.scheduled_prediction_gate", gate_block)
        self.assertNotIn("ODDS_API_KEY", gate_block)
        self.assertNotIn("ODDS_API_KEY", reserve_block)
        self.assertIn("python -m v14.api_budget record-prediction", reserve_block)
        self.assertIn("git push origin", reserve_block)
        self.assertIn("Persist the reservation before the paid request", reserve_block)

    def test_paid_prediction_is_stamped_with_objective_run_trigger(self):
        start = self.text.index("- name: Build native Pulsar V14 production payload")
        end = self.text.index("- name: Record zero-API slate coverage and rejection reasons")
        block = self.text[start:end]
        self.assertIn("ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}", block)
        self.assertIn('--run-trigger "${{ steps.gate.outputs.run_trigger }}"', block)
        self.assertIn('if: steps.gate.outputs.run_required == \'true\'', block)

    def test_hidden_scheduled_run_never_consumes_operational_bet_exposure(self):
        start = self.text.index("- name: Persist PIT predictions and decision evidence")
        end = self.text.index("- name: Capture immediate certified close only if actually due")
        block = self.text[start:end]
        self.assertIn('if [ "${{ steps.gate.outputs.run_trigger }}" = "MANUAL" ]; then', block)
        self.assertIn("python -m v14.bet_ledger record", block)
        self.assertIn("python -m v14.paper_ledger record", block)
        self.assertIn("python -m v14.tracking snapshot", block)

    def test_discord_publication_remains_manual_only(self):
        start = self.text.index("- name: Publish Pulsar V14 Discord analytics")
        end = self.text.index("- name: Archive native point-in-time state 90 days")
        block = self.text[start:end]
        self.assertIn("steps.gate.outputs.run_trigger == 'MANUAL'", block)
        self.assertIn("DISCORD_WEBHOOK_URL", block)


if __name__ == "__main__":
    unittest.main()
