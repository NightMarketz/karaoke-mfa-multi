"""Contract tests for the keyframe generator (ComfyUI handoff).

Guards the pure parts: which prompt each shared keyframe gets, template
substitution at the trust boundary, and the cache-busting nonce. The HTTP
round-trip is not exercised here; it needs a live server.
"""

import json
import unittest

from scripts.keyframes_gen import (
    build_graph,
    keyframe_jobs,
)

TEMPLATE = json.dumps({
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "quality, %prompt%"}},
    "7": {"class_type": "KSampler", "inputs": {"seed": "%seed%", "steps": 10}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "out"}},
}).replace('"%seed%"', "%seed%")


def _takes(*specs):
    """specs: (idx, section, keyframe_prompt)"""
    out = []
    for idx, section, prompt in specs:
        out.append({
            "idx": idx, "section": section,
            "kf_in": f"kf_{idx:03d}", "kf_out": f"kf_{idx + 1:03d}",
            "keyframe_prompt": prompt, "negative_prompt": "bad",
        })
    return out


class KeyframeJobTests(unittest.TestCase):
    def test_n_takes_yield_n_plus_one_jobs(self):
        takes = _takes((0, "intro", "A"), (1, "verse", "B"), (2, "chorus", "C"))
        jobs = keyframe_jobs(takes)
        self.assertEqual(len(takes) + 1, len(jobs), f"denominador: {len(takes)} takes")

    def test_each_keyframe_uses_the_prompt_of_the_take_it_starts(self):
        takes = _takes((0, "intro", "A"), (1, "verse", "B"))
        jobs = {j["id"]: j["prompt"] for j in keyframe_jobs(takes)}
        self.assertEqual("A", jobs["kf_000"])
        self.assertEqual("B", jobs["kf_001"])

    def test_the_final_keyframe_reuses_the_last_take_prompt(self):
        takes = _takes((0, "intro", "A"), (1, "verse", "B"))
        jobs = {j["id"]: j["prompt"] for j in keyframe_jobs(takes)}
        self.assertEqual("B", jobs["kf_002"], "o keyframe final fecha o ultimo take")

    def test_ids_are_unique_and_ordered(self):
        jobs = keyframe_jobs(_takes((0, "a", "A"), (1, "b", "B"), (2, "c", "C")))
        ids = [j["id"] for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), ids)

    def test_no_takes_yield_no_jobs(self):
        self.assertEqual([], keyframe_jobs([]))


class BuildGraphTests(unittest.TestCase):
    def test_markers_are_substituted_and_result_parses(self):
        g = build_graph(TEMPLATE, "a scene", 42, "pfx")
        self.assertNotIn("%prompt%", json.dumps(g))
        self.assertNotIn("%seed%", json.dumps(g))
        self.assertIn("a scene", g["5"]["inputs"]["text"])
        self.assertEqual(42, g["7"]["inputs"]["seed"])

    def test_seed_stays_a_number_not_a_string(self):
        g = build_graph(TEMPLATE, "x", 7, "pfx")
        self.assertIsInstance(g["7"]["inputs"]["seed"], int)

    def test_filename_prefix_carries_a_nonce(self):
        # Armadilha do ComfyUI: grafo identico reenviado devolve
        # execution_cached com outputs vazios.
        a = build_graph(TEMPLATE, "x", 7, "pfx")["9"]["inputs"]["filename_prefix"]
        b = build_graph(TEMPLATE, "x", 7, "pfx")["9"]["inputs"]["filename_prefix"]
        self.assertTrue(a.startswith("pfx"))
        self.assertNotEqual(a, b, "sem nonce o ComfyUI devolve cache vazio")

    def test_quote_in_prompt_cannot_break_the_json(self):
        # Fronteira de confianca: o prompt vem de song.toml, texto livre.
        g = build_graph(TEMPLATE, 'he said "hi" \\ and left', 1, "p")
        self.assertIn("hi", g["5"]["inputs"]["text"])

    def test_newline_in_prompt_cannot_break_the_json(self):
        g = build_graph(TEMPLATE, "line one\nline two", 1, "p")
        self.assertIn("line two", g["5"]["inputs"]["text"])
