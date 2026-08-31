from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/mlb-bot.yml")


class V14ProductionCloseCaptureWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_durable_prediction_persistence_precedes_immediate_close_capture(self):
        persist = self.text.index("- name: Persist PIT predictions and decision evidence")
        immediate = self.text.index("- name: Capture immediate pregame closes fail-soft")
        publish = self.text.index("- name: Publish Pulsar V14 Discord analytics")
        self.assertLess(persist, immediate)
        self.assertLess(immediate, publish)

    def test_immediate_capture_is_fail_soft_and_keeps_scheduled_fallback(self):
        start = self.text.index("- name: Capture immediate pregame closes fail-soft")
        end = self.text.index("- name: Publish Pulsar V14 Discord analytics")
        block = self.text[start:end]
        self.assertIn("continue-on-error: true", block)
        self.assertIn("ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}", block)
        self.assertIn("python -m v14.market_close_ledger capture", block)
        self.assertIn("python -m v14.market_close_ledger hydrate-paper", block)
        self.assertIn("python -m v14.official_close", block)
        self.assertIn("data/v14_market_close_report.json", block)
        self.assertIn("scheduled 10-minute close capture remains fallback", block)

    def test_core_persistence_does_not_depend_on_close_api(self):
        start = self.text.index("- name: Persist PIT predictions and decision evidence")
        end = self.text.index("- name: Capture immediate pregame closes fail-soft")
        block = self.text[start:end]
        self.assertNotIn("ODDS_API_KEY", block)
        self.assertNotIn("market_close_ledger capture", block)
        self.assertIn("git push origin", block)


if __name__ == "__main__":
    unittest.main()
