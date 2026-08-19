from __future__ import annotations

import unittest

from v11 import discord_v13 as discord


class DiscordV13VisualTests(unittest.TestCase):
    def _result(self):
        return {
            "game_pk": 12345,
            "phase": "FINAL",
            "amu": 3.9,
            "hmu": 4.8,
            "ctx": {
                "away": "Away Club",
                "home": "Home Club",
                "away_sp": "Away Starter",
                "home_sp": "Home Starter",
                "away_lineup": {"count": 9},
                "home_lineup": {"count": 9},
            },
            "model": {"version": "test-model"},
            "data_quality": {"model_input_score": .91},
            "features": {
                "weather": {
                    "available": True,
                    "temperature_c": 24,
                    "wind_kph": 12,
                    "humidity_pct": 55,
                }
            },
            "canonical_lines": {"TOTAL": 8.5},
            "options": [
                {"market": "ML", "name": "Away Club", "p_predictive_final": .421},
                {"market": "ML", "name": "Home Club", "p_predictive_final": .579},
                {"market": "RUNLINE", "name": "Away Club", "point": 1.5, "p_predictive_final": .641},
                {"market": "RUNLINE", "name": "Away Club", "point": -1.5, "p_predictive_final": .271},
                {"market": "RUNLINE", "name": "Home Club", "point": 1.5, "p_predictive_final": .729},
                {"market": "RUNLINE", "name": "Home Club", "point": -1.5, "p_predictive_final": .359},
                {"market": "TOTAL", "name": "Over", "point": 8.5, "p_predictive_final": .536},
                {"market": "TOTAL", "name": "Under", "point": 8.5, "p_predictive_final": .464},
                # Alternate totals must not replace the canonical displayed pair.
                {"market": "TOTAL", "name": "Over", "point": 9.5, "p_predictive_final": .410},
                {"market": "TOTAL", "name": "Under", "point": 9.5, "p_predictive_final": .590},
            ],
        }

    def test_scoreboard_has_exactly_eight_primary_percentages(self):
        fields = discord._scoreboard_fields(self._result())
        rendered = "\n".join(value for _name, value in fields)
        self.assertEqual(rendered.count("%"), 8)
        for expected in ("42.1%", "57.9%", "64.1%", "27.1%", "72.9%", "35.9%", "53.6%", "46.4%"):
            self.assertIn(expected, rendered)
        self.assertNotIn("41.0%", rendered)
        self.assertNotIn("59.0%", rendered)

    def test_market_sections_are_fixed_and_readable(self):
        fields = discord._scoreboard_fields(self._result())
        names = [name for name, _value in fields]
        self.assertEqual(names[:3], ["🏆 MONEYLINE", "⚾ RUN LINE ±1.5", "📊 TOTAL 8.5"])
        runline = fields[1][1]
        self.assertIn("`+1.5`", runline)
        self.assertIn("`-1.5`", runline)

    def test_missing_market_keeps_slot_instead_of_hiding_it(self):
        result = self._result()
        result["options"] = [o for o in result["options"] if not (o.get("market") == "RUNLINE" and o.get("name") == "Home Club" and o.get("point") == -1.5)]
        rendered = discord._scoreboard_fields(result)[1][1]
        self.assertIn("**—**", rendered)

    def test_game_color_is_deterministic_and_varies(self):
        self.assertEqual(discord._game_color(12345), discord._game_color(12345))
        self.assertNotEqual(discord._game_color(12345), discord._game_color(12346))


if __name__ == "__main__":
    unittest.main()
