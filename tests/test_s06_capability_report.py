"""What the ASS compiler could not deliver must be said out loud."""

import unittest

from tests._optional_imports import import_or_skip

import_or_skip("numpy")
import_or_skip("pysubs2")

from scripts.karaoke_styles.effects import EFFECTS
from scripts.karaoke_styles.keyframes import Effect, Layer, Track
from scripts.karaoke_styles.library import get_preset
from scripts.s06_generate_ass import _effect_capability_gaps


class CapabilityReportTests(unittest.TestCase):
    def test_every_shipped_effect_is_fully_deliverable(self):
        # Cardinality first: an empty registry would make this vacuously true.
        self.assertGreaterEqual(len(EFFECTS), 7)
        lines = [{"style": "verse", "effect": name} for name in EFFECTS]
        self.assertEqual({}, _effect_capability_gaps(lines, {}))

    def test_a_gap_is_reported_with_the_property_named(self):
        EFFECTS["_probe"] = Effect("_probe", (Layer("main", (
            Track("scale_y", ((0, 1.0), (90, 1.2))),
            Track("glow", ((0, 0.0), (90, 1.0))),
        )),))
        try:
            gaps = _effect_capability_gaps([{"style": "verse", "effect": "_probe"}], {})
            self.assertEqual({"_probe": ["glow"]}, gaps)
        finally:
            del EFFECTS["_probe"]

    def test_a_gap_the_STYLE_asks_for_is_reported_too(self):
        r"""The effect a line gets is not always the effect the line names.

        A plain "highlight" line is upgraded to the preset's own
        highlight_effect, so a preset asking for an undeliverable property
        renders as a bare sweep on every one of its lines. Reading
        line["effect"] alone reports nothing at all -- the loudest possible
        silence, on the exact case the report exists for.
        """
        EFFECTS["_probe_style"] = Effect("_probe_style", (Layer("main", (
            Track("gradient", ((0, 0.0), (90, 1.0))),
        )),))
        styles = dict(get_preset("word-pop").styles)
        styles["verse"] = styles["verse"].__class__(
            **{**styles["verse"].__dict__, "highlight_effect": "_probe_style"}
        )
        try:
            gaps = _effect_capability_gaps(
                [{"style": "verse", "effect": "highlight"}], styles
            )
            self.assertEqual({"_probe_style": ["gradient"]}, gaps)
        finally:
            del EFFECTS["_probe_style"]

    def test_a_text_effect_is_never_reported_as_a_gap(self):
        # typewriter has no tracks at all; asking it for unsupported_props
        # would blow up on the missing .tracks attribute.
        self.assertEqual(
            {}, _effect_capability_gaps([{"style": "verse", "effect": "typewriter"}], {})
        )


if __name__ == "__main__":
    unittest.main()
