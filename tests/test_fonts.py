"""Font file resolution and text measurement.

Skipped wholesale off Windows: the resolver reads the system font directory,
and the pipeline's presets name Windows faces.
"""

import sys
import unittest

from tests._optional_imports import import_or_skip

import_or_skip("PIL")

from scripts.karaoke_styles.fonts import FontNotFound, measure, resolve_font_path


@unittest.skipUnless(sys.platform == "win32", "resolver reads the Windows font dir")
class FontResolutionTests(unittest.TestCase):
    def test_resolves_a_face_the_presets_actually_use(self):
        path = resolve_font_path("Segoe UI Black", bold=True, italic=False)
        self.assertTrue(path.exists())
        self.assertEqual(".ttf", path.suffix.lower())

    def test_unknown_family_raises_instead_of_substituting(self):
        # libass substitutes silently; that is exactly the surprise we refuse
        # to inherit, because a substituted face invalidates every measurement.
        with self.assertRaises(FontNotFound):
            resolve_font_path("Definitely Not A Font", bold=False, italic=False)

    def test_a_family_plus_subfamily_name_still_resolves(self):
        # EVERY shipped preset says fontname="Segoe UI Bold", which is not a
        # family -- the family is "Segoe UI" and "Bold" is its subfamily. An
        # exact-family-only resolver raises FontNotFound on the entire library
        # while still passing the "Segoe UI Black" test above, because that one
        # IS a real family. Found by the Task 0 gate, not by these tests.
        path = resolve_font_path("Segoe UI Bold", bold=True, italic=False)
        self.assertTrue(path.exists())
        self.assertEqual("segoeuib.ttf", path.name.lower())

    def test_italic_is_not_traded_away_for_weight(self):
        upright = resolve_font_path("Segoe UI", bold=False, italic=False)
        italic = resolve_font_path("Segoe UI", bold=False, italic=True)
        self.assertNotEqual(upright.name.lower(), italic.name.lower())


@unittest.skipUnless(sys.platform == "win32", "needs a real font file")
class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.path = resolve_font_path("Segoe UI Black", bold=True, italic=False)

    def test_width_grows_with_text_length(self):
        short = measure("Ar", font_path=self.path, size_px=84)
        longer = measure("Arrasta", font_path=self.path, size_px=84)
        self.assertGreater(longer, short)

    def test_concatenation_is_additive_within_two_pixels(self):
        # The property the layout depends on: placing "ras" at the advance of
        # "Ar" must land where measuring "Arras" says it should.
        parts = sum(measure(s, font_path=self.path, size_px=84) for s in ("Ar", "ras"))
        whole = measure("Arras", font_path=self.path, size_px=84)
        self.assertLess(abs(parts - whole), 2.0, f"{parts} vs {whole}")

    def test_empty_text_measures_zero(self):
        self.assertEqual(0.0, measure("", font_path=self.path, size_px=84))

    def test_spacing_adds_one_gap_per_character(self):
        plain = measure("abc", font_path=self.path, size_px=84)
        spaced = measure("abc", font_path=self.path, size_px=84, spacing=5.0)
        self.assertAlmostEqual(plain + 15.0, spaced, places=3)

    def test_size_is_an_ass_fontsize_not_a_freetype_em_size(self):
        r"""The absolute-scale fence. Every other test here is scale-invariant.

        libass sizes a face so ascender + descender equals the Style's
        Fontsize; ImageFont.truetype(path, S) treats S as the em size. Reading
        one as the other makes every advance ~33% too wide, and additivity and
        monotonicity both survive that unharmed.

        169px is not computed from this module: it is what libass actually drew
        for the prefix "Arras" at Fontsize 84 in the Task 0 gate, measured as
        A_i.left - C_i.left on a real 1920x1080 ffmpeg render.
        """
        self.assertAlmostEqual(
            169.0, measure("Arras", font_path=self.path, size_px=84), delta=2.0
        )

    def test_advances_are_linear_in_the_font_size(self):
        # Measuring at the target ppem lets FreeType hinting quantise each glyph
        # advance to a whole pixel, which is systematic and accumulates along a
        # word. Measuring at a high reference ppem and scaling keeps it linear.
        one = measure("Arrastapracima", font_path=self.path, size_px=84)
        half = measure("Arrastapracima", font_path=self.path, size_px=42)
        self.assertAlmostEqual(one / 2, half, delta=0.5)


if __name__ == "__main__":
    unittest.main()
