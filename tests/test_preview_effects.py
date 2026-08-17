"""The preview builds an ASS for any effect, layout ones included."""

import unittest

from tests._optional_imports import import_or_skip

import_or_skip("PIL")
import_or_skip("numpy")
import_or_skip("pysubs2")

from scripts.karaoke_styles.effects import EFFECTS
from scripts.karaoke_styles.preview_effects import DEMO_STYLE, SYL_COUNT, build_ass


class PreviewBuildTests(unittest.TestCase):
    def test_default_showcase_covers_every_registered_effect(self):
        ass, _ = build_ass()
        self.assertGreaterEqual(len(EFFECTS), 10)
        for name in EFFECTS:
            with self.subTest(effect=name):
                self.assertIn(name, ass)

    def test_a_single_effect_can_be_previewed_alone(self):
        ass, _ = build_ass(["punch"])
        self.assertIn("punch", ass)
        self.assertNotIn("fly-in", ass)

    def test_unknown_effect_raises_instead_of_rendering_nothing(self):
        with self.assertRaises(KeyError):
            build_ass(["not-an-effect"])

    def test_a_layout_effect_gets_one_positioned_event_per_syllable(self):
        r"""The whole point of the loop: motion presets must be previewable.

        Routing them through the same inline token path as the in-place
        effects would render them as a plain sweep, so the preview would
        cheerfully show nothing wrong with an effect that does not work.
        """
        ass, _ = build_ass(["fly-in"])
        dialogues = [d for d in ass.splitlines() if d.startswith("Dialogue:")]
        lyric = [d for d in dialogues if ",Demo," in d]
        # One Dialogue per demo syllable, every one of them positioned.
        self.assertGreaterEqual(SYL_COUNT, 8)   # cardinality before the verdict
        self.assertEqual(SYL_COUNT, len(lyric))
        self.assertEqual(
            SYL_COUNT, sum(1 for d in lyric if "\\move(" in d or "\\pos(" in d)
        )

    def test_the_demo_line_is_long_enough_to_wrap(self):
        r"""The preview must exercise the multi-row path, not just claim to.

        place()'s balanced wrap, its upward stacking and its line_height were
        covered only by unit tests over synthetic widths: across 52 real lines
        of jobs/publi-bet, 0 wrapped. A demo phrase that fits on one row leaves
        that half of the layout unrendered and unlooked-at.
        """
        ass, _ = build_ass(["punch"])
        ys = {float(d.split("\\pos(")[1].split(")")[0].split(",")[1])
              for d in ass.splitlines()
              if d.startswith("Dialogue:") and ",Demo," in d and "\\pos(" in d}
        self.assertEqual(2, len(ys), f"demo line did not wrap: rows at {ys}")

    def test_rows_are_stacked_one_ass_fontsize_apart(self):
        r"""libass stacks rows by exactly the Style's Fontsize, so we must too.

        A Fontsize IS ascender + descender, which is the face's natural line
        height -- the same fact fonts.py derives measure() from. Measured on a
        burned frame of the same text: libass 74px between row baselines, and
        the line_height = ass_size * 1.2 this replaced gave 89px, dragging the
        upper row visibly higher than any non-layout preset puts it.
        """
        ass, _ = build_ass(["punch"])
        ys = sorted(
            float(d.split("\\pos(")[1].split(")")[0].split(",")[1])
            for d in ass.splitlines()
            if d.startswith("Dialogue:") and ",Demo," in d and "\\pos(" in d
        )
        self.assertEqual(
            float(DEMO_STYLE.fontsize), ys[-1] - ys[0],
            f"row spacing {ys[-1] - ys[0]} != Fontsize {DEMO_STYLE.fontsize}",
        )

    def test_an_in_place_effect_stays_on_the_single_event_path(self):
        ass, _ = build_ass(["focus"])
        lyric = [d for d in ass.splitlines()
                 if d.startswith("Dialogue:") and ",Demo," in d]
        self.assertEqual(1, len(lyric))


if __name__ == "__main__":
    unittest.main()
