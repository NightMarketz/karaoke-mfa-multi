r"""One Dialogue per syllable when the effect needs real layout.

The rules this pins:
  - the karaoke clock is unchanged (each event carries its own leading \k)
  - every syllable gets exactly one event, each with exactly one \pos
  - non-layout effects keep the single-event path untouched
"""

import re
import unittest

from tests._optional_imports import import_or_skip

import_or_skip("numpy")
import_or_skip("pysubs2")
import_or_skip("PIL")

from scripts.karaoke_styles.library import get_preset
from scripts.s06_generate_ass import _build_layout_events

LINE = {
    "start": 10.0,
    "end": 11.6,
    "style": "verse",
    "words": [{
        "word": "aah",
        "id": "L001_W001",
        "start": 10.0,
        "end": 11.6,
        "syllables": [
            {"text": "aa", "karaoke_start": 10.0, "karaoke_end": 10.8, "confidence": 0.9},
            {"text": "ah", "karaoke_start": 10.8, "karaoke_end": 11.6, "confidence": 0.9},
        ],
    }],
}


class LayoutEventTests(unittest.TestCase):
    def setUp(self):
        self.style = get_preset("word-pop").styles["verse"]

    def _events(self, effect="fly-in"):
        return _build_layout_events(
            LINE, self.style, scale=1.5, play_res=(1920, 1080),
            fade_tag=r"{\fad(300,500)}", start_ts="0:00:09.00", end_ts="0:00:12.10",
            effect=effect,
        )

    def test_one_event_per_syllable(self):
        events = self._events()
        self.assertEqual(2, len(events))
        for event in events:
            with self.subTest(event=event):
                self.assertEqual(1, event.count(r"\pos("))

    def test_syllables_do_not_share_an_x(self):
        xs = [float(re.search(r"\\pos\(([\d.]+),", e).group(1)) for e in self._events()]
        self.assertNotEqual(xs[0], xs[1])
        self.assertLess(xs[0], xs[1])   # "aa" sits left of "ah"

    def test_each_event_carries_the_full_line_karaoke_clock(self):
        # Every syllable's event runs the whole line, so each needs its own
        # leading \k to hold the fill back until its turn. Without it, all the
        # syllables fill at once from the line's first frame.
        for event in self._events()[1:]:
            with self.subTest(event=event):
                self.assertRegex(event, r"\\k\d+")

    def test_every_event_shares_the_line_window(self):
        for event in self._events():
            with self.subTest(event=event):
                self.assertIn("0:00:09.00,0:00:12.10", event)

    def test_x_is_the_measured_advance_not_merely_an_increasing_number(self):
        r"""End-to-end scale fence: font resolution -> measure -> place -> \pos.

        Ordering and stacking tests are all scale-invariant, so a wrong font
        size (or a pre-converted one) sails through them while every syllable
        sits at the wrong x. Derive the expected position independently:

            run   = w0 + w1               (one word, no internal gap)
            left  = 960 - run / 2
            pos_0 = left + w0 / 2 = 960 - w1 / 2
        """
        from scripts.karaoke_styles.fonts import measure, resolve_font_path

        path = resolve_font_path(
            self.style.fontname, bold=self.style.bold, italic=self.style.italic
        )
        size = round(self.style.fontsize * 1.5)
        w0, w1 = (measure(t, font_path=path, size_px=size) for t in ("aa", "ah"))
        xs = [float(re.search(r"\\pos\(([\d.]+),", e).group(1)) for e in self._events()]
        self.assertAlmostEqual(960.0 - w1 / 2, xs[0], places=1)
        self.assertAlmostEqual(960.0 - w1 / 2 + (w0 + w1) / 2, xs[1], places=1)

    def test_the_row_sits_where_marginv_says_it_does(self):
        r"""Layout presets must land on the same baseline as non-layout ones.

        MarginV is the distance from the bottom of the frame to the bottom of
        the text, so the anchor is \an2 and y is that bottom edge outright.
        Anchoring the middle (\an5) at the same number lifts every layout
        preset half a line above every other preset in the library.
        """
        ys = {float(re.search(r"\\pos\([\d.]+,([\d.]+)\)", e).group(1))
              for e in self._events()}
        self.assertEqual({1080.0 - round(self.style.margin_v * 1.5)}, ys)
        for event in self._events():
            self.assertIn(r"\an2", event)


if __name__ == "__main__":
    unittest.main()
