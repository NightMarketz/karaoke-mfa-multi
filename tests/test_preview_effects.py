"""The preview builds an ASS for any effect, layout ones included."""

import unittest

from tests._optional_imports import import_or_skip

import_or_skip("PIL")
import_or_skip("numpy")
import_or_skip("pysubs2")

from scripts.karaoke_styles.effects import EFFECTS
from scripts.karaoke_styles.preview_effects import build_ass


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
        # 8 demo syllables, one Dialogue each, every one of them positioned.
        self.assertEqual(8, len(lyric))
        self.assertEqual(8, sum(1 for d in lyric if "\\move(" in d or "\\pos(" in d))

    def test_an_in_place_effect_stays_on_the_single_event_path(self):
        ass, _ = build_ass(["focus"])
        lyric = [d for d in ass.splitlines()
                 if d.startswith("Dialogue:") and ",Demo," in d]
        self.assertEqual(1, len(lyric))


if __name__ == "__main__":
    unittest.main()
