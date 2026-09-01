from pathlib import Path
import unittest


WORKFLOWS = (
    Path('.github/workflows/mlb-bot.yml'),
    Path('.github/workflows/v14-close-capture.yml'),
    Path('.github/workflows/v14-performance.yml'),
    Path('.github/workflows/v14-statcast-refresh.yml'),
    Path('.github/workflows/v14-defense-refresh.yml'),
    Path('.github/workflows/v13-7-free-data-collector.yml'),
)


class V14RuntimeWorkflowIsolationTests(unittest.TestCase):
    def test_mutable_workflows_use_runtime_data_helper_not_main_branch_commits(self) -> None:
        for workflow in WORKFLOWS:
            text = workflow.read_text(encoding='utf-8')
            with self.subTest(workflow=workflow.name):
                self.assertIn('v14.state_branch', text)
                self.assertNotIn('git commit -m', text)
                self.assertNotIn('git push origin "HEAD:$GITHUB_REF_NAME"', text)

    def test_paid_workflows_hydrate_before_budget_or_close_gate(self) -> None:
        production = Path('.github/workflows/mlb-bot.yml').read_text(encoding='utf-8')
        close = Path('.github/workflows/v14-close-capture.yml').read_text(encoding='utf-8')
        self.assertLess(production.index('Hydrate mutable state from runtime-data'), production.index('Resolve manual or objective scheduled FINAL gate'))
        self.assertLess(close.index('Hydrate mutable state from runtime-data'), close.index('Bootstrap tracked games from persisted predictions'))

    def test_legacy_collector_state_is_explicitly_research_only(self) -> None:
        manifest = Path('research/v14_runtime_legacy_paths.txt').read_text(encoding='utf-8')
        self.assertIn('data/v137', manifest)
        self.assertIn('data/v13_model_health.json', manifest)
        self.assertNotIn('data/v14_predictions.jsonl', manifest)


if __name__ == '__main__':
    unittest.main()
