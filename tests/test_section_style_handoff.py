"""The style key s03b computes must survive to s05, unchanged.

s03b resolves a `[Label]` into (canonical_section, style_key) using a 56-entry
map. It used to persist only the label; s05 then re-derived the style from its
own 15-entry map, and the two disagreed on 31 of the 56 labels — `refrão` and
`final chorus` rendered with the Verse style instead of Chorus.
"""
import tempfile
import unittest
from pathlib import Path

from scripts.s03b_lyrics_align import SECTION_TO_STYLE, _parse_lyrics, _resolve_section
from scripts.s05_analyze import _segment_aware_grouper

LYRICS = """[Refrão]
Arrasta pra cima, cai na cilada

[Final Chorus]
O lucro é deles, teu prejuízo em comissão
"""


def _one_word_segment(section: str, style: str | None) -> tuple[list[dict], list[dict]]:
    """A minimal transcript segment shaped the way s03b emits them."""
    words = [{"word": "x", "start": 0.0, "end": 0.5}]
    seg: dict = {"section": section, "words": words, "text": "x"}
    if style is not None:
        seg["style"] = style
    return [seg], words


class ParseLyricsCarriesStyleTests(unittest.TestCase):
    def test_parse_lyrics_persists_the_resolved_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lyrics.txt"
            path.write_text(LYRICS, encoding="utf-8")
            lines = _parse_lyrics(path)

        self.assertEqual(2, len(lines), f"expected 2 singable lines, got {len(lines)}")
        self.assertEqual(
            ["chorus", "chorus"],
            [ln.get("style") for ln in lines],
            "refrão and final chorus must both carry the chorus style",
        )


class GrouperPrefersCarriedStyleTests(unittest.TestCase):
    def test_grouper_uses_the_style_the_segment_carries(self):
        # "refrão" is absent from s05's own map, so without the carried style
        # this falls back to verse.
        segments, words = _one_word_segment("refrão", "chorus")

        lines = _segment_aware_grouper(segments, words)

        self.assertEqual("chorus", lines[0]["style"])

    def test_grouper_still_falls_back_for_older_transcripts(self):
        # A transcript written before this change has no style field.
        segments, words = _one_word_segment("chorus", None)

        lines = _segment_aware_grouper(segments, words)

        self.assertEqual("chorus", lines[0]["style"])


class HandoffIsLosslessTests(unittest.TestCase):
    def test_every_s03b_label_reaches_s05_with_the_same_style(self):
        examined, divergent = 0, []
        for label in SECTION_TO_STYLE:
            canonical, style = _resolve_section(label)
            segments, words = _one_word_segment(canonical, style)
            got = _segment_aware_grouper(segments, words)[0]["style"]
            examined += 1
            if got != style:
                divergent.append(f"[{label}] s03b={style} s05={got}")

        self.assertGreaterEqual(
            examined, 50,
            f"only {examined} labels examined — the map shrank, this check is vacuous",
        )
        self.assertEqual(
            [], divergent,
            f"{len(divergent)}/{examined} labels change style between s03b and s05: "
            + "; ".join(divergent[:8]),
        )


class RenderedStyleTests(unittest.TestCase):
    """Agreement between the maps is not the same as being right.

    The sweep above only proves s05 stops re-deriving. These pin the style a
    listener actually sees, so picking the wrong map as the authority shows up
    here instead of passing quietly.
    """

    CASES = {
        "refrão":       "chorus",
        "refrao":       "chorus",
        "final chorus": "chorus",
        "hook":         "chorus",
        "coda":         "outro",
        # A pre-chorus has its own style in every preset; rendering it as a
        # plain verse throws that distinction away.
        "pre-chorus":   "prechorus",
        "pre chorus":   "prechorus",
        # Not in the 56-entry map — reaches the style only via the prefix
        # fallback, which had the same disagreement.
        "pre-drop":     "prechorus",
    }

    def test_labels_render_with_the_style_they_deserve(self):
        wrong = []
        for label, expected in self.CASES.items():
            canonical, style = _resolve_section(label)
            segments, words = _one_word_segment(canonical, style)
            got = _segment_aware_grouper(segments, words)[0]["style"]
            if got != expected:
                wrong.append(f"[{label}] expected {expected}, rendered {got}")

        self.assertEqual(
            [], wrong,
            f"{len(wrong)}/{len(self.CASES)} labels render with the wrong style: "
            + "; ".join(wrong),
        )


if __name__ == "__main__":
    unittest.main()
