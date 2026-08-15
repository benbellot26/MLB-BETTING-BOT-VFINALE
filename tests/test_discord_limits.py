from __future__ import annotations

import unittest
from unittest.mock import patch

from v11 import core
from v11 import discord_limits as dl


class DiscordLimitTests(unittest.TestCase):
    def tearDown(self):
        # Tests that install the wrapper restore the module-level marker so other
        # suites do not inherit presentation monkey patches accidentally.
        if hasattr(core, "_discord_original_send_embed"):
            core.send_embed = core._discord_original_send_embed
        for name in ("_discord_limits_installed", "_discord_original_send_embed"):
            if hasattr(core, name):
                delattr(core, name)
        dl._INSTALLED = False

    def test_splits_oversized_market_field_without_losing_text(self):
        paragraphs = [f"Option {i}: " + ("x" * 360) for i in range(12)]
        source = "\n\n".join(paragraphs)
        pages = dl.build_pages("Game", [("Run Line", source)])
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(dl.validate_page(page) for page in pages))
        values = "\n".join(v for page in pages for _, v in page["fields"])
        for paragraph in paragraphs:
            self.assertIn(paragraph, values)

    def test_every_discord_limit_is_respected(self):
        title = "T" * 500
        description = "D" * 5000
        fields = [("N" * 400, "V" * 2500) for _ in range(30)]
        pages = dl.build_pages(title, fields, description=description)
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertTrue(dl.validate_page(page))
            self.assertLessEqual(len(page["title"]), dl.TITLE_LIMIT)
            self.assertLessEqual(len(page.get("description") or ""), dl.DESCRIPTION_LIMIT)
            self.assertLessEqual(len(page["fields"]), dl.FIELDS_PER_EMBED_LIMIT)
            self.assertLessEqual(dl._embed_chars(page["title"], page.get("description"), page["fields"]), dl.EMBED_TOTAL_LIMIT)
            for name, value in page["fields"]:
                self.assertLessEqual(len(name), dl.FIELD_NAME_LIMIT)
                self.assertLessEqual(len(value), dl.FIELD_VALUE_LIMIT)

    def test_installed_wrapper_sends_each_safe_page(self):
        oversized = [("Totals", "A" * 5000)]
        expected_pages = dl.build_pages("MLB game", oversized)
        original = core.send_embed
        with patch.object(core, "send_embed", return_value=True) as sender:
            # Capture the patched mock as the original sender used by install().
            dl.install()
            self.assertTrue(core.send_embed("MLB game", oversized))
            self.assertEqual(sender.call_count, len(expected_pages))
        core.send_embed = original


if __name__ == "__main__":
    unittest.main()
