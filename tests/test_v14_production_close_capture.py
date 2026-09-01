from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/mlb-bot.yml")


class V14ProductionCloseCaptureWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_production_workflow_never_performs_close_acquisition(self):
        self.assertNotIn("python -m v14.cost_aware_close_capture", self.text)
        self.assertNotIn("python -m v14.market_close_ledger hydrate-paper", self.text)
        self.assertNotIn("python -m v14.market_close_ledger capture", self.text)
        self.assertNotIn("python -m v14.paper_ledger capture-close", self.text)
        self.assertNotIn("python -m v14.official_close", self.text)
        self.assertIn("dedicated v14-close-capture.yml only", self.text)

    def test_core_persistence_does_not_depend_on_close_api(self):
        start = self.text.index("- name: Persist PIT predictions and decision evidence")
        end = self.text.index("- name: Close collection policy")
        block = self.text[start:end]
        self.assertNotIn("ODDS_API_KEY", block)
        self.assertNotIn("cost_aware_close_capture", block)
        self.assertIn("python -m v14.state_branch persist", block)
        self.assertIn("research/v14_runtime_operational_paths.txt", block)
        self.assertNotIn("git push origin", block)

    def test_scheduled_final_gate_is_free_and_precedes_paid_prediction(self):
        self.assertIn("- cron: '*/10 * * * *'", self.text)
        gate = self.text.index("- name: Resolve manual or objective scheduled FINAL gate")
        quota = self.text.index("- name: Refresh provider quota with zero-credit endpoint")
        reserve = self.text.index("- name: Reserve and persist every paid Odds snapshot before request")
        paid = self.text.index("- name: Build native Pulsar V14 production payload")
        self.assertLess(gate, quota)
        self.assertLess(quota, reserve)
        self.assertLess(reserve, paid)
        gate_block = self.text[gate:quota]
        quota_block = self.text[quota:reserve]
        reserve_block = self.text[reserve:paid]
        self.assertIn("python -m v14.scheduled_prediction_gate", gate_block)
        self.assertNotIn("ODDS_API_KEY", gate_block)
        # The quota probe authenticates with the same key but uses the provider's
        # zero-credit endpoint. It must not be confused with a paid odds snapshot.
        self.assertIn("ODDS_API_KEY", quota_block)
        self.assertIn("python -m v14.odds_quota_probe", quota_block)
        self.assertIn("record-provider-state", quota_block)
        self.assertNotIn("production_runtime", quota_block)
        self.assertNotIn("ODDS_API_KEY", reserve_block)
        self.assertIn("python -m v14.api_budget record-prediction", reserve_block)
        self.assertIn("python -m v14.api_budget record-manual", reserve_block)
        self.assertIn("python -m v14.state_branch persist", reserve_block)
        self.assertIn("V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS: '50'", reserve_block)
        self.assertIn("Persist before the paid request", reserve_block)

    def test_provider_quota_is_reconciled_even_if_payload_step_fails(self):
        paid = self.text.index("- name: Build native Pulsar V14 production payload")
        reconcile = self.text.index("- name: Reconcile provider-reported quota after paid snapshot")
        coverage = self.text.index("- name: Record zero-API slate coverage and rejection reasons")
        self.assertLess(paid, reconcile)
        self.assertLess(reconcile, coverage)
        block = self.text[reconcile:coverage]
        self.assertIn("if: always() && steps.gate.outputs.run_required == 'true'", block)
        self.assertIn("record-provider-state", block)
        self.assertIn("runtime/v14/odds_provider_quota.json", block)
        self.assertIn("v14.state_branch persist", block)
        self.assertIn("provider-guard", block)
        self.assertIn("V14_ODDS_PROVIDER_EMERGENCY_RESERVE_CREDITS: '50'", block)

    def test_paid_prediction_is_stamped_with_objective_run_trigger(self):
        start = self.text.index("- name: Build native Pulsar V14 production payload")
        end = self.text.index("- name: Reconcile provider-reported quota after paid snapshot")
        block = self.text[start:end]
        self.assertIn("ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}", block)
        self.assertIn('--run-trigger "${{ steps.gate.outputs.run_trigger }}"', block)
        self.assertIn("if: steps.gate.outputs.run_required == 'true'", block)

    def test_hidden_scheduled_run_never_consumes_operational_bet_exposure(self):
        start = self.text.index("- name: Persist PIT predictions and decision evidence")
        end = self.text.index("- name: Close collection policy")
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
