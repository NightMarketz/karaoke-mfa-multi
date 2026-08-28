"""Contract tests for the take planner (handoff to the video-generation machine).

The load-bearing property is arithmetic: consecutive takes SHARE a boundary
keyframe, and each take yields more frames than the slot it occupies so the
surplus can pay for the crossfade. Get this wrong and 35 seams accumulate
~8.75 s of drift, silently desynchronising the video from the lyrics.
"""

import unittest

from scripts.takes_plan import (
    DEFAULT_FPS,
    DEFAULT_OVERLAP_FRAMES,
    DEFAULT_TAKE_FRAMES,
    keyframe_ids,
    plan_takes,
)


def _line(style, start, end, text="x"):
    return {"text": text, "start": start, "end": end, "style": style,
            "color": "default", "effect": "highlight", "words": []}


class SlotArithmeticTests(unittest.TestCase):
    def test_slot_is_take_minus_overlap(self):
        # 81 gerados, 4 pagam o crossfade, 77 ocupam a linha do tempo
        self.assertEqual(81, DEFAULT_TAKE_FRAMES)
        self.assertEqual(4, DEFAULT_OVERLAP_FRAMES)
        self.assertEqual(16, DEFAULT_FPS)

    def test_takes_tile_the_timeline_without_gap_or_overlap(self):
        lines = [_line("verse", 0.0, 20.0)]
        takes = plan_takes(lines)
        self.assertGreater(len(takes), 0, "conjunto vazio nao e' aprovacao")
        for a, b in zip(takes, takes[1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=6,
                                   msg="buraco ou sobreposicao na linha do tempo")

    def test_slot_duration_matches_the_frame_budget(self):
        lines = [_line("verse", 0.0, 30.0)]
        takes = plan_takes(lines)
        slot_s = (DEFAULT_TAKE_FRAMES - DEFAULT_OVERLAP_FRAMES) / DEFAULT_FPS
        full = [t for t in takes if not t["trimmed"]]
        self.assertGreater(len(full), 0, "nenhum take cheio para medir")
        for t in full:
            self.assertAlmostEqual(slot_s, t["end"] - t["start"], places=6)

    def test_coverage_closes_with_the_source_duration(self):
        lines = [_line("verse", 0.0, 12.0), _line("chorus", 12.0, 25.0)]
        takes = plan_takes(lines)
        covered = sum(t["end"] - t["start"] for t in takes)
        self.assertAlmostEqual(25.0, covered, places=6,
                               msg="soma das partes tem de fechar com o total")


class SharedKeyframeTests(unittest.TestCase):
    def test_n_takes_need_n_plus_one_keyframes(self):
        lines = [_line("verse", 0.0, 40.0)]
        takes = plan_takes(lines)
        ids = keyframe_ids(takes)
        self.assertEqual(len(takes) + 1, len(ids),
                         f"denominador: {len(takes)} takes")

    def test_consecutive_takes_share_the_boundary_keyframe(self):
        lines = [_line("verse", 0.0, 40.0)]
        takes = plan_takes(lines)
        self.assertGreater(len(takes), 1, "precisa de 2+ takes para haver emenda")
        for a, b in zip(takes, takes[1:]):
            self.assertEqual(a["kf_out"], b["kf_in"],
                             "a emenda so' e' coerente se o keyframe for o MESMO")

    def test_keyframe_ids_are_unique_and_ordered(self):
        lines = [_line("verse", 0.0, 40.0)]
        ids = keyframe_ids(plan_takes(lines))
        self.assertEqual(len(ids), len(set(ids)), "id de keyframe repetido")
        self.assertEqual(sorted(ids), ids)


class SectionBoundaryTests(unittest.TestCase):
    def test_a_take_never_straddles_two_sections(self):
        lines = [_line("verse", 0.0, 10.0), _line("chorus", 10.0, 20.0)]
        takes = plan_takes(lines)
        self.assertGreater(len(takes), 0)
        for t in takes:
            self.assertIn(t["section"], {"verse", "chorus"})
        boundaries = {round(t["start"], 6) for t in takes}
        self.assertIn(10.0, boundaries, "o corte tem de cair na troca de secao")

    def test_short_section_still_gets_one_take(self):
        lines = [_line("intro", 0.0, 1.5), _line("verse", 1.5, 10.0)]
        takes = plan_takes(lines)
        intro = [t for t in takes if t["section"] == "intro"]
        self.assertEqual(1, len(intro), "secao curta perdeu o take")
        self.assertTrue(intro[0]["trimmed"])

    def test_every_take_declares_the_frames_to_generate(self):
        lines = [_line("verse", 0.0, 20.0)]
        takes = plan_takes(lines)
        for t in takes:
            self.assertEqual(DEFAULT_TAKE_FRAMES, t["generate_frames"],
                             "o modelo sempre gera a janela nativa")


class EmptyInputTests(unittest.TestCase):
    def test_no_lines_produces_no_takes(self):
        self.assertEqual([], plan_takes([]))

    def test_no_takes_produces_no_keyframes(self):
        self.assertEqual([], keyframe_ids([]))
