from pathlib import Path
import unittest


WORKFLOW = Path('.github/workflows/v14-generation-identity.yml')


class V14GenerationIdentityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding='utf-8')

    def test_generation_reset_is_zero_odds_and_runtime_data_only(self) -> None:
        self.assertIn('Hydrate mutable runtime evidence', self.text)
        self.assertIn('v14.state_branch persist', self.text)
        self.assertNotIn('ODDS_API_KEY', self.text)
        self.assertNotIn('v14.acquisition', self.text)
        self.assertNotIn('git commit -m', self.text)

    def test_reset_rebuilds_authoritative_current_generation_artifacts(self) -> None:
        for token in (
            'v14.tracking report',
            'v14.probability_calibration fit',
            'v14.uncertainty_fit',
            'v14.sharp_benchmark',
            'v14.certification import load_status',
        ):
            self.assertIn(token, self.text)


if __name__ == '__main__':
    unittest.main()
