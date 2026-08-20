r"""Layers: three roles, one main, a ceiling of four, and Layer 0 for main-only.

The three rules here are each a measurement, not a preference:

  * fill colour is REFUSED on a main layer because \kf sweeps SecondaryColour
    -> PrimaryColour, so a track writing \1c writes the register the fill reads
    from. Measured: animating \1c, setting \1c statically and animating \1a all
    stop the sweep dead, while \3c and \2c leave it alone.
  * the ceiling is FOUR because layer cost is linear in burn time -- 538 events
    burn 60s of 1920x1080 in 4.5s, 2152 events in 13.4s, 8608 in 49.4s -- and 4
    keeps a 3-minute song at roughly 40s.
  * a main-only effect must number Layer 0, byte for byte what shipped before
    layers existed.
"""

import unittest

from scripts.karaoke_styles.keyframes import (
    MAIN_REFUSED,
    MAX_LAYERS,
    ROLE_Z,
    Effect,
    Layer,
    Track,
)


class LayerRoleTests(unittest.TestCase):
    def test_the_roles_are_exactly_three(self):
        self.assertEqual({"under", "main", "over"}, set(ROLE_Z))

    def test_an_unknown_role_is_refused_at_definition_time(self):
        with self.assertRaises(ValueError) as caught:
            Layer("glow")
        self.assertIn("glow", str(caught.exception))

    def test_fill_colour_on_a_main_layer_is_refused_BY_NAME(self):
        # Fence 1. Not "ignored", not "dropped": named in the error, because a
        # silently-dropped fill track is a dead karaoke sweep that nobody sees
        # until they watch the burned video.
        for prop in sorted(MAIN_REFUSED):
            with self.subTest(prop=prop):
                with self.assertRaises(ValueError) as caught:
                    Layer("main", (Track(prop, ((0, "#FF0000") if "color" in prop else (0, 0.5),)),))
                message = str(caught.exception)
                self.assertIn(prop, message)
                self.assertIn("sweep", message)

    def test_the_same_props_are_free_on_an_under_or_over_layer(self):
        # This is the whole point of the roles: the two rules compose instead
        # of fighting. Non-main layers carry \k, not \kf -- no sweep to kill.
        for role in ("under", "over"):
            with self.subTest(role=role):
                layer = Layer(role, (
                    Track("fill_color", ((0, "#FF0000"),)),
                    Track("fill_alpha", ((0, 0.5),)),
                ))
                self.assertEqual(2, len(layer.tracks))

    def test_outline_and_unsung_colour_are_free_on_main(self):
        # Measured: \3c and \2c leave the sweep alive. Refusing them would be
        # superstition, and it would make colour flare cost an extra event.
        layer = Layer("main", (
            Track("outline_color", ((0, "#000000"), (200, "#FF00FF"))),
            Track("unsung_color", ((0, "#888888"),)),
            Track("shadow_color", ((0, "#000000"),)),
        ))
        self.assertEqual(3, len(layer.tracks))

    def test_a_main_layer_may_not_be_offset(self):
        with self.assertRaises(ValueError):
            Layer("main", (), offset=(4.0, 0.0))


class EffectShapeTests(unittest.TestCase):
    def test_exactly_one_main_layer_is_required(self):
        with self.assertRaises(ValueError):
            Effect("none", (Layer("under"),))
        with self.assertRaises(ValueError):
            Effect("two", (Layer("main"), Layer("main")))
        self.assertEqual(1, len(Effect("ok", (Layer("main"),)).layers))

    def test_the_ceiling_is_four_layers(self):
        # Fence 3.
        four = tuple([Layer("under"), Layer("under"), Layer("main"), Layer("over")])
        self.assertEqual(MAX_LAYERS, len(four))
        Effect("four", four)                       # at the ceiling: fine
        with self.assertRaises(ValueError) as caught:
            Effect("five", four + (Layer("over"),))
        self.assertIn(str(MAX_LAYERS), str(caught.exception))

    def test_tracks_are_flattened_across_every_layer(self):
        effect = Effect("e", (
            Layer("under", (Track("blur", ((0, 6.0),)),)),
            Layer("main", (Track("outline", ((0, 2.0),)),)),
        ))
        self.assertEqual({"blur", "outline"}, effect.props())
        self.assertEqual(2, len(effect.tracks))

    def test_needs_layout_sees_a_layout_prop_on_any_layer(self):
        self.assertFalse(Effect("a", (Layer("main", (Track("blur", ((0, 1.0),)),)),)).needs_layout)
        self.assertTrue(Effect("b", (
            Layer("under", (Track("offset_x", ((0, 3.0),)),)),
            Layer("main"),
        )).needs_layout)

    def test_main_returns_the_one_main_layer(self):
        main = Layer("main", (Track("blur", ((0, 1.0),)),))
        self.assertIs(main, Effect("e", (Layer("under"), main, Layer("over"))).main)


class LayerNumberingTests(unittest.TestCase):
    def test_a_main_only_effect_is_layer_zero(self):
        # Fence 2. Byte for byte what shipped before layers existed, which is
        # why the golden needs no hand-written exception.
        self.assertEqual((0,), Effect("e", (Layer("main"),)).layer_numbers)

    def test_an_under_plus_main_effect_numbers_zero_then_one(self):
        effect = Effect("e", (Layer("under"), Layer("main")))
        self.assertEqual((0, 1), effect.layer_numbers)

    def test_the_whole_set_is_translated_so_its_minimum_is_zero(self):
        self.assertEqual((0, 1, 2), Effect("e", (Layer("under"), Layer("main"), Layer("over"))).layer_numbers)
        self.assertEqual((0, 1), Effect("f", (Layer("main"), Layer("over"))).layer_numbers)

    def test_two_layers_in_the_same_role_share_a_number(self):
        # Chromatic aberration is two ghosts; both sit under, both draw before
        # main, and their order between themselves is file order.
        effect = Effect("e", (Layer("under"), Layer("under"), Layer("main")))
        self.assertEqual((0, 0, 1), effect.layer_numbers)

    def test_under_always_numbers_below_main(self):
        # ASS draws lower Layer first, so this ordering IS the z-order.
        for layers in (
            (Layer("under"), Layer("main")),
            (Layer("under"), Layer("main"), Layer("over")),
        ):
            with self.subTest(count=len(layers)):
                effect = Effect("e", layers)
                numbers = dict(zip((l.role for l in layers), effect.layer_numbers))
                self.assertLess(numbers["under"], numbers["main"])


from scripts.karaoke_styles.effects import EFFECTS, syllable_ass
from scripts.karaoke_styles.library import get_preset
from scripts.ass_emit import build_line_events


def _demo_line():
    """One analysis.json-shaped line: two words, three syllables."""
    def syl(text, start, end):
        return {"text": text, "start": start, "end": end,
                "karaoke_start": start, "karaoke_end": end, "confidence": 1.0}
    return {
        "start": 1.0, "end": 2.2, "style": "verse",
        "words": [
            {"word": "sol", "start": 1.0, "end": 1.4,
             "syllables": [syl("sol", 1.0, 1.4)]},
            {"word": "brilha", "start": 1.5, "end": 2.2,
             "syllables": [syl("bri", 1.5, 1.85), syl("lha", 1.85, 2.2)]},
        ],
    }


def _events(effect, style_effect=None, preset="pill"):
    style = get_preset(preset).styles["verse"]
    return build_line_events(
        _demo_line(), style,
        effect=effect, style_effect=style_effect or effect, style_key="verse",
        scale=1.5, play_res=(1920, 1080), margin_lr=96,
        fade_tag="{\\fad(120,120)}",
        start_ts="0:00:00.70", end_ts="0:00:02.50",
        start_ms=700, line_start_ms=1000,
    )


class EmittedLayerTests(unittest.TestCase):
    def test_every_shipped_effect_emits_one_event_per_layer_per_path(self):
        # Cardinality first: an empty EFFECTS would make every claim below a
        # universal green.
        self.assertGreaterEqual(len(EFFECTS), 10)
        checked = 0
        for name, effect in EFFECTS.items():
            with self.subTest(effect=name):
                layers = 1 if not hasattr(effect, "layers") else len(effect.layers)
                events = _events(name)
                if effect.needs_layout:
                    self.assertEqual(0, len(events) % layers, (name, len(events)))
                    self.assertEqual(3 * layers, len(events))  # 3 syllables
                else:
                    self.assertEqual(layers, len(events))
                checked += 1
        self.assertEqual(len(EFFECTS), checked)

    def test_a_main_only_effect_emits_layer_zero_and_inherited_margins(self):
        # Fence 2, end to end. "0,0,0" means "inherit the style row" -- exactly
        # what every shipped line has carried since before layers existed.
        events = _events("highlight")
        self.assertEqual(1, len(events))
        self.assertTrue(events[0].startswith("Dialogue: 0,"), events[0])
        self.assertIn(",0,0,0,,", events[0])

    def test_the_karaoke_clock_is_identical_on_every_layer(self):
        # The one invariant no effect may touch. Same clock on every copy, or
        # the layers drift apart against the audio.
        import re
        for name, effect in EFFECTS.items():
            if not hasattr(effect, "layers") or effect.needs_layout:
                continue
            with self.subTest(effect=name):
                clocks = {
                    sum(int(n) for n in re.findall(r"\\k[fo]?(\d+)", event))
                    for event in _events(name)
                }
                self.assertEqual(1, len(clocks), (name, clocks))

    def test_only_the_main_layer_carries_the_sweep(self):
        effect = EFFECTS["highlight"]
        self.assertEqual("main", effect.main.role)
        self.assertIn("\\kf", _events("highlight")[0])


class SyllableLayerTests(unittest.TestCase):
    def test_layer_index_selects_which_layer_is_rendered(self):
        self.assertIn("\\kf", syllable_ass("highlight", 40, "x", layer_index=0))

    def test_an_out_of_range_layer_index_raises_rather_than_returning_nothing(self):
        with self.assertRaises(IndexError):
            syllable_ass("highlight", 40, "x", layer_index=1)


if __name__ == "__main__":
    unittest.main()
