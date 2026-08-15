from __future__ import annotations

import unittest

from v11 import predictive_v124 as v124
from v11 import v124_statcast_provider as provider


class V124StatcastProviderTests(unittest.TestCase):
    def test_parser_finds_player_and_xwoba(self):
        html = """
        <html><body>
        <table><tr><th>Other</th></tr><tr><td>x</td></tr></table>
        <table>
          <tr><th>Player</th><th>Year</th><th>wOBA</th><th>xwOBA</th><th>Hard Hit %</th></tr>
          <tr><td>Alvarez, Yordan</td><td>2026</td><td>.441</td><td>.475</td><td>53.1</td></tr>
        </table>
        </body></html>
        """
        idx = provider._parse_statcast_table(html, v124)
        row = idx[("name", v124._norm("Yordan Alvarez"))]
        self.assertEqual(row["xwOBA"], ".475")

    def test_parser_fails_neutral_without_expected_table(self):
        idx = provider._parse_statcast_table("<table><tr><th>Player</th></tr><tr><td>A</td></tr></table>", v124)
        self.assertEqual(idx, {})


if __name__ == "__main__":
    unittest.main()
