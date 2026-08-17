r"""The keyframe -> libass tag compiler.

Every emitted \t time is absolute from the DIALOGUE LINE start, because that
is the clock libass runs \t on. A compiler that anchors at 0 animates every
syllable of the line simultaneously on the first frame.
"""

import unittest

from scripts.karaoke_styles.ass_compile import (
    compile_syllable,
    unsupported_props,
)
from scripts.karaoke_styles.keyframes import Effect, Track


class CompileSyllableTests(unittest.TestCase):
    def test_first_key_becomes_a_static_tag_and_the_rest_become_transforms(self):
        effect = Effect("pop", (Track("scale_y", ((0, 1.0), (90, 1.24), (240, 1.0))),))
        out = compile_syllable(effect, text="ta", duration_cs=40, attack_ms=800)
        self.assertEqual(
            r"{\fscy100\t(800,890,\fscy124)\t(890,1040,\fscy100)\kf40}ta", out
        )

    def test_alpha_is_inverted_into_ass_transparency(self):
        # neutral 0.0 = invisible, 1.0 = opaque; ASS &HFF& = invisible.
        effect = Effect("reveal", (Track("alpha", ((0, 0.0), (140, 1.0))),))
        out = compile_syllable(effect, text="x", duration_cs=20, attack_ms=0)
        self.assertEqual(r"{\alpha&HFF&\t(0,140,\alpha&H00&)\kf20}x", out)

    def test_accel_is_written_when_it_is_not_linear(self):
        effect = Effect("e", (Track("blur", ((0, 4.0), (200, 0.0)), accel=0.5),))
        out = compile_syllable(effect, text="x", duration_cs=20, attack_ms=100)
        self.assertIn(r"\t(100,300,0.5,\blur0)", out)

    def test_a_single_key_emits_no_transform_at_all(self):
        effect = Effect("e", (Track("outline", ((0, 6.0),)),))
        out = compile_syllable(effect, text="x", duration_cs=20, attack_ms=0)
        self.assertEqual(r"{\bord6\kf20}x", out)
        self.assertNotIn(r"\t(", out)

    def test_zero_length_interval_is_skipped(self):
        # Two keys at the same resolved millisecond would emit \t(500,500,...),
        # which libass treats as an instant jump and is noise in the output.
        effect = Effect("e", (Track("alpha", ((0, 0.0), (0, 1.0), (100, 1.0))),))
        out = compile_syllable(effect, text="x", duration_cs=20, attack_ms=500)
        self.assertNotIn("(500,500", out)

    def test_effect_with_no_tracks_is_the_plain_sweep(self):
        out = compile_syllable(Effect("highlight", ()), text="x", duration_cs=20, attack_ms=0)
        self.assertEqual(r"{\kf20}x", out)

    def test_duration_is_floored_to_one_centisecond(self):
        out = compile_syllable(Effect("e", ()), text="x", duration_cs=0, attack_ms=0)
        self.assertEqual(r"{\kf1}x", out)


class CapabilityTests(unittest.TestCase):
    def test_future_properties_are_reported_not_dropped(self):
        effect = Effect("cine", (
            Track("scale_y", ((0, 1.0), (90, 1.2))),
            Track("glow", ((0, 0.0), (90, 1.0))),
            Track("gradient", ((0, 0.0),)),
        ))
        self.assertEqual({"glow", "gradient"}, unsupported_props(effect))

    def test_a_fully_supported_effect_reports_nothing(self):
        effect = Effect("pop", (Track("scale_y", ((0, 1.0), (90, 1.2))),))
        self.assertEqual(set(), unsupported_props(effect))

    def test_unsupported_property_emits_no_tag(self):
        effect = Effect("cine", (Track("glow", ((0, 0.0), (90, 1.0))),))
        out = compile_syllable(effect, text="x", duration_cs=20, attack_ms=0)
        self.assertEqual(r"{\kf20}x", out)


if __name__ == "__main__":
    unittest.main()
