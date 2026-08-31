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
        # The workflow must not independently trigger paid market/paper/official
        # close acquisition; the unified wrapper shares one in-memory snapshot.
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


if __name__ == "__main__":
    unittest.main()
