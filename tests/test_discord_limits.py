from __future__ import annotations

import unittest

from v11 import core
from v11 import discord_limits as dl


class DiscordLimitTests(unittest.TestCase):
    def test_splits_oversized_market_field_without_losing_text(self):
        paragraphs = [f"Option {i}: " + ("x" * 360) for i in range(12)]
        source = "\n\n".join(paragraphs)
        pages = dl.build_pages("Game", [("Run Line", source)])
        expanded = [(n, v) for page in pages for n, v in page["fields"]]
        self.assertGreater(len(expanded), 1)
        self.assertTrue(all(dl.validate_page(page) for page in pages))
        values = "\n".join(v for _, v in expanded)
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
        real_sender = core.send_embed
        calls = []

        def fake_sender(title, fields, color=5763719, description=None):
            calls.append((title, fields, color, description))
            return True

        try:
            core.send_embed = fake_sender
            for name in ("_discord_limits_installed", "_discord_original_send_embed"):
                if hasattr(core, name):
                    delattr(core, name)
            dl._INSTALLED = False
            dl.install()
            self.assertTrue(core.send_embed("MLB game", oversized))
            self.assertEqual(len(calls), len(expected_pages))
            for title, fields, color, description in calls:
                self.assertTrue(dl.validate_page({
                    "title": title, "fields": fields, "color": color, "description": description,
                }))
        finally:
            core.send_embed = real_sender
            for name in ("_discord_limits_installed", "_discord_original_send_embed"):
                if hasattr(core, name):
                    delattr(core, name)
            dl._INSTALLED = False


if __name__ == "__main__":
    unittest.main()
