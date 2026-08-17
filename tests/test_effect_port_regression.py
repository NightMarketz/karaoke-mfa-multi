"""The port to keyframes must not change a single emitted token.

Golden captured from the pre-port implementation. flash/focus/pop/reveal are
expected to match byte for byte; highlight/none/typewriter are unchanged code
paths and are in here as controls.
"""

import json
import unittest
from pathlib import Path

from scripts.karaoke_styles.effects import EFFECTS, syllable_ass

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "effect_tokens.json").read_text(encoding="utf-8")
)
CASES = ((40, "ta", 800), (7, "a", 0), (3, "aaa", 1234), (100, "lá", 55))


class EffectPortRegressionTests(unittest.TestCase):
    def test_every_golden_effect_still_exists(self):
        # The golden pins the SEVEN effects that existed before the port. Later
        # tasks add more, so this is containment, not equality -- but the seven
        # must all still be there, hence the count on both sides.
        self.assertEqual(7, len(GOLDEN))
        self.assertEqual(7, len(set(GOLDEN) & set(EFFECTS)))

    def test_tokens_are_unchanged_by_the_port(self):
        for name, expected in GOLDEN.items():
            for (cs, txt, off), want in zip(CASES, expected):
                with self.subTest(effect=name, text=txt, offset=off):
                    self.assertEqual(want, syllable_ass(name, cs, txt, offset_ms=off))


if __name__ == "__main__":
    unittest.main()
