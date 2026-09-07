r"""shine: one mask, not a generic vector clip.

Generic \clip is a large vocabulary in exchange for one look, so it stays out
until something needs it. `shine` carries a single normalised number -- 0.0 is
a band entirely left of the frame, 1.0 entirely right of it -- and compiles to
\clip plus \t(\clip(...)).

It works in FRAME coordinates, not text coordinates. On the layout path each
syllable's box is known, but off it the line's extent is not known without
measuring, and measuring there would force any preset wanting shine to become
a layout preset. The band crosses the frame instead: visually near-identical
on a centred line that occupies most of the width, and available on both paths.
"""

import re
import unittest

from scripts.karaoke_styles.ass_compile import (
    SHINE_HALF_WIDTH,
    _shine_clip,
    compile_layer,
)
from scripts.karaoke_styles.effects import shine_layer
from scripts.karaoke_styles.keyframes import MASK_PROPS, Layer, Track

FRAME = (1920, 1080)


def _rect(clip: str) -> tuple[int, int, int, int]:
    """The four numbers of a \\clip rectangle: x1, y1, x2, y2."""
    return tuple(int(n) for n in re.findall(r"-?\d+", clip))


class ShineBandTests(unittest.TestCase):
    def test_the_band_is_an_axis_aligned_rectangle_not_a_vector_drawing(self):
        # Measured, not preferred. On this libass an animated RECTANGULAR clip
        # sweeps 581px across three instants, while the same band written as a
        # vector drawing and animated through \t does not move at all -- and
        # the static vector form DOES draw, with its two endpoint shapes 407px
        # apart, so the frozen reading is a real verdict and not a measurement
        # over nothing. A skewed vector band would never sweep on the machine
        # that burns the video. This test is the fence against someone
        # "improving" it back into a diagonal.
        clip = _shine_clip(0.5, FRAME)
        self.assertTrue(clip.startswith("\\clip("), clip)
        self.assertNotIn("m ", clip)
        self.assertNotIn(" l ", clip)
        self.assertEqual(4, len(re.findall(r"-?\d+", clip)))

    def test_it_spans_the_full_frame_height(self):
        _, y1, _, y2 = _rect(_shine_clip(0.5, FRAME))
        self.assertEqual(0, y1)
        self.assertEqual(FRAME[1], y2)

    def test_zero_puts_the_whole_band_left_of_the_frame(self):
        x1, _, x2, _ = _rect(_shine_clip(0.0, FRAME))
        self.assertLess(max(x1, x2), 0)

    def test_one_puts_the_whole_band_right_of_the_frame(self):
        x1, _, x2, _ = _rect(_shine_clip(1.0, FRAME))
        self.assertGreater(min(x1, x2), FRAME[0])

    def test_the_band_marches_right_as_the_value_rises(self):
        # Cardinality and monotonicity together: a probe that sampled one
        # instant could not tell a moving band from a stuck one -- which is
        # exactly the mistake that shipped the vector version.
        centres = []
        for step in range(11):
            x1, _, x2, _ = _rect(_shine_clip(step / 10, FRAME))
            centres.append((x1 + x2) / 2)
        self.assertEqual(11, len(centres))
        for before, after in zip(centres, centres[1:]):
            self.assertLess(before, after)

    def test_the_band_is_wide_enough_to_be_soft(self):
        # It crosses the FRAME, so a narrow band would miss a short line
        # entirely. Documented risk, bounded here.
        x1, _, x2, _ = _rect(_shine_clip(0.5, FRAME))
        self.assertGreater(abs(x2 - x1), FRAME[0] * SHINE_HALF_WIDTH)

    def test_the_left_edge_stays_left_of_the_right_edge(self):
        # libass reads \clip as (x1,y1,x2,y2); a band emitted with its
        # coordinates crossed clips nothing at all, silently.
        for step in range(11):
            with self.subTest(value=step / 10):
                x1, _, x2, _ = _rect(_shine_clip(step / 10, FRAME))
                self.assertLess(x1, x2)


class ShineCompilationTests(unittest.TestCase):
    def test_a_shine_track_compiles_to_a_resting_clip_plus_transforms(self):
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0)), time="abs"),))
        out = compile_layer(
            layer, text="x", duration_cs=40, attack_ms=1234, frame=FRAME, karaoke="k"
        )
        # "\\clip(m" was the vector-drawing marker of the first (skewed) band;
        # the rectangular form is "\\clip(x1,y1,x2,y2)" with no "m", so the
        # substring check drops it -- the assertion still verifies exactly one
        # resting clip plus one \t-wrapped clip, which is what this test names.
        self.assertEqual(1, out.count("\\clip(") - out.count("\\t(0,900,\\clip("))
        self.assertIn("\\t(0,900,\\clip(", out)

    def test_abs_time_ignores_the_syllable_attack(self):
        # A line-wide sweep must be the SAME animation on every syllable, or
        # each token would drag its own band along behind it.
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0)), time="abs"),))
        first = compile_layer(layer, text="x", duration_cs=40, attack_ms=0,
                              frame=FRAME, karaoke="k")
        later = compile_layer(layer, text="x", duration_cs=40, attack_ms=1234,
                              frame=FRAME, karaoke="k")
        self.assertEqual(first, later)

    def test_ms_time_still_follows_the_attack(self):
        # The control for the test above: if `ms` mode did not shift either,
        # that test would prove nothing about `abs`.
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0))),))
        first = compile_layer(layer, text="x", duration_cs=40, attack_ms=0,
                              frame=FRAME, karaoke="k")
        later = compile_layer(layer, text="x", duration_cs=40, attack_ms=1234,
                              frame=FRAME, karaoke="k")
        self.assertNotEqual(first, later)
        self.assertIn("\\t(1234,2134,", later)

    def test_a_shine_track_without_a_frame_raises_instead_of_dropping_the_mask(self):
        layer = Layer("over", (Track("shine", ((0, 0.0), (900, 1.0)), time="abs"),))
        with self.assertRaises(ValueError) as caught:
            compile_layer(layer, text="x", duration_cs=40, attack_ms=0, karaoke="k")
        self.assertIn("frame", str(caught.exception))

    def test_shine_is_the_only_mask_property(self):
        self.assertEqual({"shine"}, set(MASK_PROPS))


class ShineLayerTests(unittest.TestCase):
    def test_it_builds_an_over_layer_that_draws_above_main(self):
        layer = shine_layer()
        self.assertEqual("over", layer.role)
        self.assertIn("shine", {track.prop for track in layer.tracks})

    def test_both_colour_registers_are_pinned_so_the_copy_is_uniform(self):
        # The over layer carries \k, so without \2c the not-yet-sung half of
        # the copy would draw at the STYLE's waiting colour and the sweep would
        # read as two different lights.
        props = {track.prop for track in shine_layer().tracks}
        self.assertIn("fill_color", props)
        self.assertIn("unsung_color", props)

    def test_the_sweep_is_measured_from_the_dialogue_not_the_syllable(self):
        shine = next(t for t in shine_layer().tracks if t.prop == "shine")
        self.assertEqual("abs", shine.time)
        self.assertEqual((0.0, 1.0), tuple(v for _, v in shine.keys))


if __name__ == "__main__":
    unittest.main()
