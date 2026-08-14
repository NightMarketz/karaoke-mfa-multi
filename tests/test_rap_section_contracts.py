"""[Rap] must resolve as a known section, not fall through to the unknown path."""
import tempfile
import unittest
from pathlib import Path

from scripts.s03b_lyrics_align import SECTION_TO_STYLE, _parse_lyrics
from scripts.karaoke_styles.library import (
    PRESET_LIBRARY,
    STYLE_DEFAULTS,
    supported_style_keys,
)

LYRICS = """[Chorus]
É publi, é publi, é publi de ilusão

[Rap]
Acorda menor, esse brilho é cenário
Cordão no pescoço e contrato milionário
"""


class RapSectionTests(unittest.TestCase):
    def test_rap_is_registered_in_the_map(self):
        self.assertIn("rap", SECTION_TO_STYLE)
        self.assertEqual("rap", SECTION_TO_STYLE["rap"])

    def test_rap_lines_carry_no_unknown_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lyrics.txt"
            path.write_text(LYRICS, encoding="utf-8")
            lines = _parse_lyrics(path)

        self.assertEqual(3, len(lines), f"expected 3 singable lines, got {len(lines)}")
        rap_lines = [ln for ln in lines if ln["section"] == "rap"]
        self.assertEqual(2, len(rap_lines), "the two [Rap] lines must be tagged 'rap'")
        markers = [m for ln in lines for m in ln["unknown_markers"]]
        self.assertEqual([], markers, f"[Rap] still reported as unknown: {markers}")


class RapStyleKeyTests(unittest.TestCase):
    def test_rap_is_a_supported_style_key(self):
        self.assertIn("rap", supported_style_keys())
        self.assertIn("rap", STYLE_DEFAULTS)

    def test_rap_section_maps_to_the_rap_style(self):
        self.assertEqual("rap", SECTION_TO_STYLE["rap"])

    def test_every_preset_still_validates(self):
        from scripts.karaoke_styles.library import validate_all_presets

        self.assertEqual([], validate_all_presets())

    def test_presets_without_a_rap_style_degrade_to_verse(self):
        # s06 falls back at scripts/s06_generate_ass.py:722; this asserts the
        # premise that lets us add 'rap' to some presets and not others.
        for preset_id, preset in PRESET_LIBRARY.items():
            if "rap" not in preset.styles:
                self.assertIn("verse", preset.styles,
                              f"{preset_id} has neither rap nor verse to fall back to")

    def test_stages_take_their_whitelist_from_the_library(self):
        # s05 and s08 must not carry their own copy of the style key set:
        # one source of truth, so a new key cannot be half-registered.
        import scripts.s05_analyze as s05
        import scripts.s08_validate as s08

        for module in (s05, s08):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn(
                '"ad_lib"}', source,
                f"{module.__name__} still hardcodes a style whitelist literal",
            )
            self.assertIn("supported_style_keys", source,
                          f"{module.__name__} must call supported_style_keys()")


if __name__ == "__main__":
    unittest.main()
