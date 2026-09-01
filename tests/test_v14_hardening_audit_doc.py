from pathlib import Path
import unittest


class V14HardeningAuditDocTests(unittest.TestCase):
    def test_audit_contract_keeps_challengers_non_production(self) -> None:
        text = Path('research/V14_HARDENING_AUDIT.md').read_text(encoding='utf-8')
        self.assertIn('do not alter V14.6 probabilities', text)
        self.assertIn('no staking increase', text)
        self.assertIn('no certification-threshold reduction', text)
        self.assertIn('runtime-data', text)


if __name__ == '__main__':
    unittest.main()
