r"""Colour tracks: authored as #RRGGBB, emitted as libass &HBBGGRR&.

Colour is NOT interpolated in Python -- \t interpolates it, so only the
endpoints are ever emitted. A three-key colour track emits two \t's and no
intermediate colour at all, which is what these tests pin.
"""

import unittest

from scripts.karaoke_styles.ass_compile import _ass_colour, compile_layer
from scripts.karaoke_styles.keyframes import Layer, Track


def _tags(layer, **kw):
    r"""Compile one layer's tags.

    Task 3 made the layer, not the effect, the thing that compiles. These cases
    run on an UNDER layer because \1c and \1a are refused on a main one -- they
    write the register \kf sweeps -- and the emitted tag is identical either
    way, which is what this file is about.
    """
    kw.setdefault("text", "x")
    kw.setdefault("duration_cs", 40)
    kw.setdefault("attack_ms", 0)
    return compile_layer(layer, **kw)


class ColourConversionTests(unittest.TestCase):
    def test_hex_is_byte_reversed_into_ass_order(self):
        # ASS stores &HBBGGRR&: the byte order is reversed from web hex, which
        # is the single most common way to get a colour silently wrong.
        self.assertEqual("&H0000FF&", _ass_colour("#FF0000"))   # red
        self.assertEqual("&HFF0000&", _ass_colour("#0000FF"))   # blue
        self.assertEqual("&H00FF00&", _ass_colour("#00FF00"))   # green

    def test_the_hash_is_optional_and_case_is_normalised(self):
        self.assertEqual("&HEFBEAD&", _ass_colour("adbeef"))
        self.assertEqual("&HEFBEAD&", _ass_colour("#AdBeEf"))

    def test_a_malformed_colour_is_refused_not_silently_truncated(self):
        for bad in ("#FFF", "", "#GGGGGG", "12345678"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    _ass_colour(bad)


class ColourTrackTests(unittest.TestCase):
    def test_each_colour_prop_writes_its_own_register(self):
        cases = {
            "fill_color": "\\1c",
            "unsung_color": "\\2c",
            "outline_color": "\\3c",
            "shadow_color": "\\4c",
        }
        for prop, tag in cases.items():
            with self.subTest(prop=prop):
                out = _tags(Layer("under", (Track(prop, ((0, "#FF0000"),)),)))
                self.assertIn(f"{tag}&H0000FF&", out)

    def test_each_alpha_prop_writes_its_own_register_and_inverts(self):
        # Neutral 1.0 = fully visible; ASS alpha is transparency, so it inverts.
        cases = {
            "fill_alpha": "\\1a",
            "outline_alpha": "\\3a",
            "shadow_alpha": "\\4a",
        }
        for prop, tag in cases.items():
            with self.subTest(prop=prop):
                out = _tags(Layer("under", (Track(prop, ((0, 1.0),)),)))
                self.assertIn(f"{tag}&H00&", out)
                out = _tags(Layer("under", (Track(prop, ((0, 0.0),)),)))
                self.assertIn(f"{tag}&HFF&", out)

    def test_only_the_endpoints_are_emitted_never_an_interpolated_colour(self):
        # Three keys -> a resting static plus exactly two \t's, each carrying a
        # colour that was AUTHORED. Nothing in between is computed here: libass
        # does the interpolation, and a Python-side midpoint would be a second,
        # differently-rounded answer to the same question.
        effect = Layer("under", (
            Track("outline_color", ((0, "#000000"), (100, "#FF00FF"), (300, "#000000"))),
        ))
        out = _tags(effect)
        self.assertEqual(2, out.count("\\t("))
        self.assertIn("\\3c&H000000&\\t(0,100,\\3c&HFF00FF&)\\t(100,300,\\3c&H000000&)", out)

    def test_a_colour_track_is_anchored_on_the_attack_like_any_other(self):
        effect = Layer("under", (Track("outline_color", ((0, "#000000"), (100, "#FFFFFF"))),))
        out = _tags(effect, attack_ms=1234)
        self.assertIn("\\t(1234,1334,", out)


if __name__ == "__main__":
    unittest.main()
