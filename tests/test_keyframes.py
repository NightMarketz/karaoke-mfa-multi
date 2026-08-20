"""Contract tests for the engine-neutral keyframe model."""

import unittest

from scripts.karaoke_styles.keyframes import (
    FUTURE_PROPS,
    Effect,
    Track,
    resolve,
)


class TrackResolutionTests(unittest.TestCase):
    def test_ms_keys_are_offset_by_the_syllable_attack(self):
        track = Track("scale_y", ((0, 1.0), (90, 1.24), (240, 1.0)))
        self.assertEqual(
            [(800, 1.0), (890, 1.24), (1040, 1.0)],
            resolve(track, attack_ms=800, duration_ms=400),
        )

    def test_frac_keys_scale_with_the_syllable_duration(self):
        track = Track("blur", ((0.0, 3.0), (1.0, 0.0)), time="frac")
        self.assertEqual(
            [(800, 3.0), (1200, 0.0)],
            resolve(track, attack_ms=800, duration_ms=400),
        )

    def test_negative_time_lands_before_the_attack(self):
        # "the word flies in 300ms before it is sung"
        track = Track("offset_y", ((-300, -80.0), (0, 0.0)))
        self.assertEqual(
            [(500, -80.0), (800, 0.0)],
            resolve(track, attack_ms=800, duration_ms=400),
        )

    def test_resolved_time_never_goes_negative(self):
        # A lead-in longer than the line's own head would ask libass to animate
        # before the Dialogue exists; \t clamps silently, so clamp explicitly.
        track = Track("alpha", ((-500, 0.0), (0, 1.0)))
        self.assertEqual([(0, 0.0), (200, 1.0)], resolve(track, attack_ms=200, duration_ms=400))

    def test_a_colour_value_survives_resolve_instead_of_being_coerced(self):
        # resolve() used to call float() on every value. With colour in the
        # vocabulary the value is no longer always numeric, so only the TIME
        # stays arithmetic.
        track = Track("fill_color", ((0, "#FF00AA"), (100, "#00FFAA")))
        self.assertEqual(
            [(500, "#FF00AA"), (600, "#00FFAA")],
            resolve(track, attack_ms=500, duration_ms=400),
        )

    def test_numeric_values_are_still_floats_after_resolve(self):
        track = Track("blur", ((0, 3), (100, 0)))
        values = [v for _, v in resolve(track, attack_ms=0, duration_ms=400)]
        self.assertEqual([3.0, 0.0], values)
        for value in values:
            self.assertIsInstance(value, float)


class VocabularyTests(unittest.TestCase):
    def test_unknown_property_is_rejected_at_definition_time(self):
        with self.assertRaises(ValueError) as caught:
            Track("wobble", ((0, 1.0),))
        self.assertIn("wobble", str(caught.exception))

    def test_future_property_is_accepted_but_flagged(self):
        # glow/gradient/motion_blur/audio belong to the vocabulary so the ASS
        # compiler can refuse them by name instead of ignoring them.
        for prop in FUTURE_PROPS:
            with self.subTest(prop=prop):
                self.assertEqual(prop, Track(prop, ((0, 1.0),)).prop)
        self.assertEqual(4, len(FUTURE_PROPS))

    def test_track_needs_at_least_one_key(self):
        with self.assertRaises(ValueError):
            Track("alpha", ())

    def test_time_mode_must_be_ms_or_frac(self):
        with self.assertRaises(ValueError):
            Track("alpha", ((0, 1.0),), time="seconds")


class EffectTests(unittest.TestCase):
    def test_effect_needs_layout_only_for_layout_properties(self):
        in_place = Effect("a", (Track("scale_y", ((0, 1.0), (90, 1.2))),))
        moving = Effect("b", (Track("offset_x", ((0, -40.0), (120, 0.0))),))
        self.assertFalse(in_place.needs_layout)
        self.assertTrue(moving.needs_layout)


if __name__ == "__main__":
    unittest.main()
