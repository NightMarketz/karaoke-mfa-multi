"""Line wrapping and per-syllable placement.

Pure geometry over supplied widths — no font, no ASS — so it runs everywhere.
"""

import unittest

from scripts.karaoke_styles.layout import _greedy, place, wrap


class WrapTests(unittest.TestCase):
    def test_everything_on_one_line_when_it_fits(self):
        self.assertEqual([[0, 1, 2]], wrap(["a", "b", "c"], [10, 10, 10], 5, 1000))

    def test_breaks_when_the_next_token_would_cross_the_margin(self):
        self.assertEqual([[0, 1], [2]], wrap(["a", "b", "c"], [40, 40, 40], 5, 100))

    def test_lines_are_balanced_not_greedily_filled(self):
        # Greedy would give [[0,1,2],[3]] — three tokens then a lonely one.
        # WrapStyle 0 balances, so the same two lines should be evened out.
        self.assertEqual(
            [[0, 1], [2, 3]], wrap(["a", "b", "c", "d"], [40, 40, 40, 40], 5, 140)
        )

    def test_balancing_does_not_give_up_when_one_budget_misses(self):
        r"""Greedy strands the last token; balancing has to actually rescue it.

        The first version tried a single budget (total / row count) and fell
        back to the greedy result whenever that budget happened to produce a
        different number of rows -- which is most of the time. Rendered, that
        was a full row followed by one lonely word while libass, on the same
        text, split it evenly.
        """
        widths = [100.0] * 5
        # Greedy fits four then strands the fifth.
        self.assertEqual([[0, 1, 2, 3], [4]], _greedy(widths, [10.0] * 5, 450))
        rows = wrap([str(i) for i in range(5)], widths, 10, 450)
        self.assertEqual(2, len(rows))
        self.assertGreaterEqual(len(rows[-1]), 2, f"last row still stranded: {rows}")

    def test_a_token_wider_than_the_margin_gets_its_own_line(self):
        # Never silently drop it: one over-wide line beats vanished lyrics.
        self.assertEqual([[0], [1]], wrap(["huge", "b"], [500, 20], 5, 100))

    def test_no_token_is_ever_lost(self):
        widths = [37, 12, 61, 44, 29, 55, 18]
        lines = wrap([str(i) for i in range(7)], widths, 6, 150)
        self.assertEqual(list(range(7)), sorted(i for line in lines for i in line))


class WordIntegrityTests(unittest.TestCase):
    r"""A row break may only fall where a space does.

    wrap() sees syllables, and nothing about a syllable says which word it
    belongs to except space_after: 0 means "glued to the next one". Without
    that, a break lands wherever the margin happens to fall and the lyrics
    come apart mid-word -- "dorme" rendering as "dor" ending one row and "me"
    opening the next, which is what the first wrapping preview actually drew.
    """

    # "Brilha estrela dorme": 2 + 3 + 2 syllables, gaps only after words.
    WIDTHS = [40.0] * 7
    GAPS = [0.0, 20.0, 0.0, 0.0, 20.0, 0.0, 0.0]

    def _rows(self, max_width):
        return place(
            [str(i) for i in range(7)], widths=self.WIDTHS, space_after=self.GAPS,
            max_width=max_width, centre_x=500, bottom_y=900, line_height=80,
        )

    def test_a_break_never_falls_inside_a_word(self):
        words = [(0, 1), (2, 3, 4), (5, 6)]
        for max_width in (150, 200, 250, 300):
            with self.subTest(max_width=max_width):
                placed = self._rows(max_width)
                self.assertEqual(7, len(placed))
                row_of = {int(p.text): p.y for p in placed}
                for word in words:
                    rows = {row_of[i] for i in word}
                    self.assertEqual(1, len(rows), f"word {word} split across {rows}")

    def test_a_word_wider_than_the_margin_still_gets_a_row_of_its_own(self):
        # Never silently drop it, and never split it either: an over-wide row
        # beats vanished or broken lyrics.
        placed = self._rows(60)
        self.assertEqual(7, len(placed))
        self.assertEqual(3, len({p.y for p in placed}))


class PlaceTests(unittest.TestCase):
    def test_a_single_line_is_centred_on_centre_x(self):
        placed = place(
            ["ab", "cd"], widths=[40, 60], space_after=[10, 0],
            max_width=1000, centre_x=500, bottom_y=900, line_height=80,
        )
        # total = 40 + 10 + 60 = 110, so the run starts at 500 - 55 = 445.
        self.assertEqual([445.0, 495.0], [p.x for p in placed])
        self.assertEqual([900.0, 900.0], [p.y for p in placed])

    def test_wrapped_lines_stack_upward_from_the_bottom(self):
        placed = place(
            ["ab", "cd"], widths=[80, 80], space_after=[10, 0],
            max_width=100, centre_x=500, bottom_y=900, line_height=80,
        )
        # Two lines: the last sits on bottom_y, the first one line-height above.
        self.assertEqual([820.0, 900.0], [p.y for p in placed])
        self.assertEqual([460.0, 460.0], [p.x for p in placed])

    def test_placement_covers_every_syllable(self):
        placed = place(
            [str(i) for i in range(7)], widths=[40] * 7, space_after=[8] * 7,
            max_width=200, centre_x=500, bottom_y=900, line_height=80,
        )
        self.assertEqual(7, len(placed))

    def test_syllables_inside_a_word_do_not_pay_for_a_space(self):
        r"""Wrapping must use the REAL per-syllable gaps, not one uniform space.

        space_after is 0 between syllables of a word and non-zero only at word
        boundaries. Collapsing it to a single scalar charges a space between
        every syllable, so a line of 20 syllables in 5 words is measured as if
        it had 19 spaces instead of 4 and breaks far too early.
        """
        # Two words of three syllables: ONE gap, after index 2.
        syls = ["ar", "ras", "ta", "pra", "ci", "ma"]
        gaps = [0.0, 0.0, 20.0, 0.0, 0.0, 0.0]
        placed = place(
            syls, widths=[40] * 6, space_after=gaps,
            max_width=280, centre_x=500, bottom_y=900, line_height=80,
        )
        # True run is 6*40 + 20 = 260 and fits. Charging a 20px space between
        # every syllable makes it 340 and splits the word across two rows.
        self.assertEqual(6, len(placed))
        self.assertEqual({900.0}, {p.y for p in placed})
        self.assertEqual(370.0, placed[0].x)          # 500 - 260/2
        self.assertEqual(20.0, placed[3].x - placed[2].x - 40.0)  # the one gap


if __name__ == "__main__":
    unittest.main()
