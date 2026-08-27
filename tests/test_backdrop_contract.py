"""Contract tests for the procedural backdrop (fatia A)."""

import unittest

from scripts.karaoke_styles.backdrop import BACKDROP_PALETTE, backdrop_for_color
from scripts.karaoke_styles.library import STYLE_DEFAULTS

_RANGES = {"hue": (-180.0, 180.0), "saturation": (-1.0, 1.0), "intensity": (-1.0, 1.0)}


class PaletteCoverageTests(unittest.TestCase):
    def test_every_colour_used_by_style_defaults_has_a_palette_entry(self):
        used = {v["color"] for v in STYLE_DEFAULTS.values()}
        self.assertEqual(5, len(used), f"eixo de cor mudou: {sorted(used)}")
        self.assertEqual(used, set(BACKDROP_PALETTE), "paleta divergiu de STYLE_DEFAULTS")

    def test_palette_has_no_orphan_entries(self):
        used = {v["color"] for v in STYLE_DEFAULTS.values()}
        self.assertEqual(set(), set(BACKDROP_PALETTE) - used)

    def test_every_style_resolves_to_a_backdrop(self):
        resolved = [backdrop_for_color(v["color"]) for v in STYLE_DEFAULTS.values()]
        self.assertEqual(len(STYLE_DEFAULTS), len(resolved))
        self.assertEqual(9, len(resolved), "denominador: 9 styles")

    def test_all_values_are_inside_the_filter_ranges(self):
        checked = 0
        for colour, params in BACKDROP_PALETTE.items():
            self.assertEqual({"hue", "saturation", "intensity"}, set(params), colour)
            for param, value in params.items():
                low, high = _RANGES[param]
                self.assertIsInstance(value, float, f"{colour}.{param}")
                self.assertGreaterEqual(value, low, f"{colour}.{param}")
                self.assertLessEqual(value, high, f"{colour}.{param}")
                checked += 1
        self.assertEqual(15, checked, "denominador: 5 cores x 3 params")

    def test_unknown_colour_falls_back_to_neutral(self):
        self.assertEqual(
            {"hue": 0.0, "saturation": 0.0, "intensity": 0.0},
            backdrop_for_color("nao-existe"),
        )
