"""[Rap] must resolve as a known section, not fall through to the unknown path."""
import tempfile
import unittest
from pathlib import Path

from scripts.s03b_lyrics_align import SECTION_TO_STYLE, _parse_lyrics

LYRICS = """[Chorus]
É publi, é publi, é publi de ilusão

[Rap]
Acorda menor, esse brilho é cenário
Cordão no pescoço e contrato milionário
"""


class RapSectionTests(unittest.TestCase):
    def test_rap_is_registered_in_the_map(self):
        self.assertIn("rap", SECTION_TO_STYLE)
        self.assertEqual("verse", SECTION_TO_STYLE["rap"])

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


if __name__ == "__main__":
    unittest.main()
