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

import re
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

    def test_two_layers_in_the_same_role_get_DISTINCT_numbers(self):
        # Chromatic aberration is two ghosts, both under, both drawn before
        # main. They must not share a Layer: libass runs collision avoidance
        # between events on the same Layer, so two copies numbered 0 do not sit
        # a few pixels apart -- the second is pushed onto a row of its own.
        # Burned, with a single-event control pinning the reference row: one
        # event alone occupies rows 258-292; two copies on Layer 0 occupy
        # 194-228 AND 258-292, a full row apart; the same two on Layer 0 and
        # Layer 1 share 258-292, which is the ghost the design asks for.
        effect = Effect("e", (Layer("under"), Layer("under"), Layer("main")))
        self.assertEqual((0, 1, 2), effect.layer_numbers)
        self.assertEqual(3, len(set(effect.layer_numbers)))

    def test_no_two_layers_of_any_shipped_effect_share_a_number(self):
        from scripts.karaoke_styles.effects import EFFECTS

        checked = 0
        for name, effect in EFFECTS.items():
            if not hasattr(effect, "layers"):
                continue                      # TextEffect: one layer, no numbering
            with self.subTest(effect=name):
                numbers = effect.layer_numbers
                self.assertEqual(len(effect.layers), len(numbers))
                self.assertEqual(len(numbers), len(set(numbers)), (name, numbers))
                checked += 1
        # Cardinality: an EFFECTS with no layered effects would pass the loop.
        self.assertGreaterEqual(checked, 10)

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
        #
        # ponytail: every SHIPPED effect is main-only, so this loop compares a
        # set built from ONE event and cannot fail on its own. It is a smoke
        # pass, not the fence. The fence is TwoLayerClockTests below, which
        # registers an effect that really has two layers. The counters here
        # exist only so this loop cannot degrade into a pass over nothing.
        import re
        compared = 0
        for name, effect in EFFECTS.items():
            if not hasattr(effect, "layers") or effect.needs_layout:
                continue
            with self.subTest(effect=name):
                events = _events(name)
                clocks = {
                    sum(int(n) for n in re.findall(r"\\k[fo]?(\d+)", event))
                    for event in events
                }
                self.assertEqual(1, len(clocks), (name, clocks))
                # A clock of 0 means the regex matched nothing, which would
                # make the line above true for the wrong reason.
                self.assertNotIn(0, clocks, (name, clocks))
                compared += len(events)
        # Cardinality: six main-only effects ship today, one event each.
        self.assertGreaterEqual(compared, 6, compared)

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


class TwoLayerClockTests(unittest.TestCase):
    r"""The karaoke clock, on an effect that actually HAS more than one layer.

    Every shipped effect is main-only, so any loop over EFFECTS compares a set
    of one and is green by construction. This registers a real two-layer effect
    so the invariant has something to be wrong about.
    """

    PROBE = "_clockprobe"

    def setUp(self):
        EFFECTS[self.PROBE] = Effect(self.PROBE, (
            Layer("under", (Track("blur", ((0, 6.0),)),)),
            Layer("main"),
        ))
        # addCleanup, not try/finally: it runs even when the assertion below
        # raises, so a red test cannot leave the registry poisoned for the rest
        # of the session.
        self.addCleanup(EFFECTS.pop, self.PROBE)

    def _clocks(self, events):
        return [
            sum(int(n) for n in re.findall(r"\\k[fo]?(\d+)", event))
            for event in events
        ]

    def test_both_layers_spend_exactly_the_same_karaoke_time(self):
        events = _events(self.PROBE)
        # Cardinality first, with the denominator: two layers, two events, two
        # clocks compared. One event would make the equality below vacuous.
        self.assertEqual(2, len(events), events)
        clocks = self._clocks(events)
        self.assertEqual(2, len(clocks))
        self.assertNotIn(0, clocks, clocks)
        self.assertEqual(clocks[0], clocks[1], clocks)

    def test_only_the_main_layer_sweeps_but_the_under_layer_still_advances(self):
        r"""\k draws no glyph, it only advances the clock.

        That is the whole reason the fill-colour prohibition does not reach a
        non-main layer: there is no sweep on it to kill.
        """
        under, main = _events(self.PROBE)
        self.assertNotIn(r"\kf", under)
        self.assertIn(r"\kf", main)
        self.assertIn(r"\k", under)

    def test_under_draws_first_and_main_draws_over_it(self):
        under, main = _events(self.PROBE)
        self.assertTrue(under.startswith("Dialogue: 0,"), under)
        self.assertTrue(main.startswith("Dialogue: 1,"), main)


class LayerOffsetTests(unittest.TestCase):
    r"""Layer.offset end to end, on both emit paths.

    Off the layout path the offset becomes the event's OWN MarginL/MarginR/
    MarginV, because the syllable carries no \pos to move. On the layout path
    it folds straight into the anchor, because it does.
    """

    OFFSET = (4.0, 2.0)

    def _register(self, name, tracks=()):
        EFFECTS[name] = Effect(name, (
            Layer("under", tracks, offset=self.OFFSET),
            Layer("main"),
        ))
        self.addCleanup(EFFECTS.pop, name)

    def test_an_offset_layer_writes_margins_while_main_keeps_inheriting(self):
        # Measured arithmetic, re-derived here rather than restated: with
        # alignment 2 the text is centred between the event's own MarginL and
        # MarginR, so centre_x = W/2 + (L - R)/2, and MarginV counts up from
        # the bottom. margin_lr=96 and dx=4 give 100/92 -- a centre 4px right.
        self._register("_ghostprobe")
        under, main = _events("_ghostprobe")
        style = get_preset("pill").styles["verse"]
        mv = round(style.margin_v * 1.5 - self.OFFSET[1])
        self.assertEqual(94, mv)                       # style margin_v 64 * 1.5 - 2
        self.assertIn(",100,92,94,,", under)
        self.assertIn(f",100,92,{mv},,", under)
        # 0,0,0 means "inherit the style row" -- NOT zero margins.
        self.assertIn(",0,0,0,,", main)

    def test_the_offset_moves_the_centre_by_exactly_dx(self):
        # (L - R)/2 = (100 - 92)/2 = 4. Stated as arithmetic on the emitted
        # numbers so a sign flip in either margin is caught, not just a value.
        self._register("_ghostcentre")
        under, _ = _events("_ghostcentre")
        ml, mr, mv = (int(n) for n in re.search(
            r",(\d+),(\d+),(\d+),,", under).groups())
        self.assertEqual(self.OFFSET[0], (ml - mr) / 2)
        self.assertEqual(96, (ml + mr) / 2)            # the base margin, unmoved
        self.assertEqual(94, mv)

    def test_on_the_layout_path_the_offset_folds_into_the_anchor(self):
        # scale is a LAYOUT_PROP, so this effect takes the \pos path. The track
        # sits on the under layer only: needs_layout reads every layer, and it
        # keeps main's anchor provably untouched.
        self._register("_ghostmove", (Track("scale", ((0, 1.0), (120, 1.1))),))
        events = _events("_ghostmove")
        # 3 syllables x 2 layers, under first.
        self.assertEqual(6, len(events), len(events))
        pairs = list(zip(events[:3], events[3:]))
        self.assertEqual(3, len(pairs))

        def pos(event):
            found = re.search(r"\\pos\(([\d.-]+),([\d.-]+)\)", event)
            self.assertIsNotNone(found, event)
            return float(found.group(1)), float(found.group(2))

        for under, main in pairs:
            with self.subTest(under=under):
                ux, uy = pos(under)
                mx, my = pos(main)
                self.assertAlmostEqual(self.OFFSET[0], ux - mx, places=1)
                self.assertAlmostEqual(self.OFFSET[1], uy - my, places=1)

    def test_a_main_only_effect_still_emits_no_margins_of_its_own(self):
        # The control for the two above: no offset anywhere, nothing written.
        self.assertIn(",0,0,0,,", _events("highlight")[0])


from scripts.karaoke_styles.effects import ghost_layer, glow_layer


class LayerConstructorTests(unittest.TestCase):
    def test_glow_builds_an_under_layer_that_is_wider_and_softer(self):
        layer = glow_layer(color="#38E8FF", blur=9.0, spread=5.0, alpha=0.6)
        self.assertEqual("under", layer.role)
        props = {track.prop: track.keys[0][1] for track in layer.tracks}
        self.assertEqual(9.0, props["blur"])
        self.assertEqual(5.0, props["outline"])
        self.assertEqual("#38E8FF", props["fill_color"])
        self.assertEqual("#38E8FF", props["outline_color"])
        self.assertEqual(0.6, props["alpha"])

    def test_glow_is_static_so_it_never_emits_a_transform(self):
        # A glow that animates is a different effect. Every track is one key,
        # which compiles to a resting tag and no \t at all.
        for track in glow_layer().tracks:
            with self.subTest(prop=track.prop):
                self.assertEqual(1, len(track.keys))

    def test_ghost_carries_its_displacement_as_a_static_offset(self):
        layer = ghost_layer(-4.0, 2.0, "#00E5FF")
        self.assertEqual("under", layer.role)
        self.assertEqual((-4.0, 2.0), layer.offset)
        props = {track.prop: track.keys[0][1] for track in layer.tracks}
        self.assertEqual("#00E5FF", props["fill_color"])
        self.assertEqual("#00E5FF", props["outline_color"])

    def test_ghost_needs_no_layout_which_is_the_whole_point(self):
        # If a ghost forced needs_layout, any preset wanting chromatic
        # aberration would become a layout preset and multiply its event count
        # by ten. The T0 gate exists so it does not have to.
        effect = Effect("aberration", (
            ghost_layer(-4.0, 0.0, "#00E5FF"),
            ghost_layer(4.0, 0.0, "#FF006E"),
            Layer("main"),
        ))
        self.assertFalse(effect.needs_layout)
        # Distinct, not (0, 0, 1): two ghosts sharing a Layer collide and the
        # second is pushed onto its own row. See the DISTINCT test above.
        self.assertEqual((0, 1, 2), effect.layer_numbers)


class GhostDisplacementTests(unittest.TestCase):
    """The margin arithmetic, against the numbers the T0 gate measured."""

    def _margins(self, event):
        fields = event.split(",")
        return tuple(int(f) for f in fields[5:8])

    def test_an_offset_layer_writes_its_own_margins_off_the_layout_path(self):
        from scripts.karaoke_styles.keyframes import Effect as _E
        import scripts.karaoke_styles.effects as fx
        fx.EFFECTS["_ghosttest"] = _E("_ghosttest", (
            ghost_layer(-6.0, 3.0, "#00E5FF"),
            Layer("main"),
        ))
        try:
            events = _events("_ghosttest")
        finally:
            del fx.EFFECTS["_ghosttest"]
        self.assertEqual(2, len(events))
        ghost, main = events
        # centre_x = W/2 + (L - R)/2, so dx=-6 needs L = 96-6, R = 96+6.
        # MarginV is the distance from the BOTTOM, so dy=+3 (down) needs
        # V = round(margin_v * scale) - 3.
        base_v = round(get_preset("pill").styles["verse"].margin_v * 1.5)
        self.assertEqual((90, 102, base_v - 3), self._margins(ghost))
        # The main layer is untouched: 0,0,0 means "inherit the style row".
        self.assertEqual((0, 0, 0), self._margins(main))
        self.assertTrue(ghost.startswith("Dialogue: 0,"))
        self.assertTrue(main.startswith("Dialogue: 1,"))

    def test_a_margin_never_reaches_zero_because_zero_means_inherit(self):
        # The trap the T0 gate turned up: an event margin of 0 is "use the
        # style's", not "no margin". A ghost whose dx reaches the base margin
        # would otherwise silently halve its own displacement.
        from scripts.karaoke_styles.keyframes import Effect as _E
        import scripts.karaoke_styles.effects as fx
        fx.EFFECTS["_farghost"] = _E("_farghost", (
            ghost_layer(999.0, 999.0, "#00E5FF"),
            Layer("main"),
        ))
        try:
            ghost = _events("_farghost")[0]
        finally:
            del fx.EFFECTS["_farghost"]
        for value in self._margins(ghost):
            self.assertGreaterEqual(value, 1)


if __name__ == "__main__":
    unittest.main()
