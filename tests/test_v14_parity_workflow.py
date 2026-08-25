from pathlib import Path
import unittest


class V14ParityWorkflowTests(unittest.TestCase):
    def test_parity_workflow_is_manual_and_has_no_discord_credential(self):
        text = Path('.github/workflows/v14-native-parity.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', text)
        self.assertNotIn('schedule:', text)
        self.assertNotIn('DISCORD_WEBHOOK_URL', text)
        self.assertNotIn('v14.production_runtime --send-persisted', text)
        self.assertNotIn('Publish Pulsar V14 Discord', text)
        self.assertIn("V12_DEFER_DISCORD: '1'", text)

    def test_parity_workflow_requires_non_publishing_evidence(self):
        text = Path('.github/workflows/v14-native-parity.yml').read_text(encoding='utf-8')
        self.assertIn("candidate.get('role') != 'CANDIDATE_NON_PUBLISHING'", text)
        self.assertIn("parity.get('cutover_authorized') is not False", text)
        self.assertIn("assessment.get('publication_authorized') is not False", text)
        self.assertIn('market probability leaked into native model features', text)
        self.assertIn('native_parity_assessment.json', text)
        self.assertIn('actions/upload-artifact@v4', text)


if __name__ == '__main__':
    unittest.main()
