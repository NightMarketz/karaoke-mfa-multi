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


class LayoutPropertyTests(unittest.TestCase):
    def test_scale_drives_both_axes(self):
        effect = Effect("e", (Track("scale", ((0, 1.0), (120, 1.3))),))
        out = compile_syllable(
            effect, text="x", duration_cs=20, attack_ms=0, anchor=(100.0, 500.0)
        )
        self.assertIn(r"\fscx100\fscy100", out)
        self.assertIn(r"\t(0,120,\fscx130\fscy130)", out)

    def test_rotation_pins_its_origin_to_the_anchor(self):
        # Without \org libass rotates around the frame's centre, which throws a
        # side-of-frame syllable clean off screen.
        effect = Effect("e", (Track("rotate", ((0, -12.0), (150, 0.0))),))
        out = compile_syllable(
            effect, text="x", duration_cs=20, attack_ms=0, anchor=(100.0, 500.0)
        )
        self.assertIn(r"\org(100,500)", out)
        self.assertIn(r"\frz-12", out)
        self.assertIn(r"\t(0,150,\frz0)", out)

    def test_org_is_emitted_once_however_many_rotate_tracks(self):
        effect = Effect("e", (
            Track("rotate", ((0, -12.0), (150, 0.0))),
            Track("rotate", ((150, 0.0), (300, 4.0))),
        ))
        out = compile_syllable(
            effect, text="x", duration_cs=20, attack_ms=0, anchor=(100.0, 500.0)
        )
        self.assertEqual(1, out.count(r"\org("))

    def test_offset_becomes_a_move_from_the_anchor(self):
        effect = Effect("e", (Track("offset_y", ((-300, -80.0), (0, 0.0))),))
        out = compile_syllable(
            effect, text="x", duration_cs=20, attack_ms=800, anchor=(100.0, 500.0)
        )
        self.assertIn(r"\move(100,420,100,500,500,800)", out)

    def test_both_offset_axes_share_one_move(self):
        effect = Effect("e", (
            Track("offset_x", ((-200, -40.0), (0, 0.0))),
            Track("offset_y", ((-200, -80.0), (0, 0.0))),
        ))
        out = compile_syllable(
            effect, text="x", duration_cs=20, attack_ms=800, anchor=(100.0, 500.0)
        )
        self.assertEqual(1, out.count(r"\move("))
        self.assertIn(r"\move(60,420,100,500,600,800)", out)

    def test_layout_property_without_an_anchor_is_reported_not_emitted(self):
        effect = Effect("e", (Track("rotate", ((0, -12.0), (150, 0.0))),))
        out = compile_syllable(effect, text="x", duration_cs=20, attack_ms=0)
        self.assertNotIn(r"\frz", out)
        self.assertEqual({"rotate"}, unsupported_props(effect, anchored=False))

    def test_anchored_compile_reports_only_future_props(self):
        effect = Effect("e", (
            Track("rotate", ((0, -12.0), (150, 0.0))),
            Track("glow", ((0, 0.0), (90, 1.0))),
        ))
        self.assertEqual({"glow"}, unsupported_props(effect, anchored=True))


if __name__ == "__main__":
    unittest.main()
