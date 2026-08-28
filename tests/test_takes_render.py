"""Contract tests for the FLF2V take runner (remote ComfyUI handoff).

Guards the three things that break silently: substitution at the trust
boundary (the prompt is free text from song.toml), the splice offsets when a
section ends early, and the refusal of a take whose frame count is wrong.
"""

import http.server
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import unittest

from scripts.takes_render import (
    concat_filter,
    find_gaps,
    splice_offsets,
    build_graph,
    render_all,
    montage,
    probe_frames,
    render_jobs,
    verify_take,
)

TEMPLATE = json.dumps({
    "3": {"class_type": "LoadImage", "inputs": {"image": "%first%"}},
    "4": {"class_type": "LoadImage", "inputs": {"image": "%last%"}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "quality, %prompt%"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "%negative%"}},
    "7": {"class_type": "KSampler", "inputs": {"seed": "%seed%", "steps": 10}},
    "8": {"class_type": "WanFirstLastFrameToVideo", "inputs": {"length": "%frames%"}},
    "9": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "out"}},
}).replace('"%seed%"', "%seed%").replace('"%frames%"', "%frames%")


def _takes(*specs):
    """specs: (idx, section, start, end) -> takes.json shape."""
    out = []
    for idx, section, start, end in specs:
        out.append({
            "idx": idx, "section": section, "start": start, "end": end,
            "generate_frames": 81, "overlap_frames": 4, "fps": 16,
            "kf_in": f"kf_{idx:03d}", "kf_out": f"kf_{idx + 1:03d}",
            "motion_prompt": f"motion {section}",
            "keyframe_prompt": f"still {section}",
            "negative_prompt": "blurry",
            "trimmed": (end - start) < 4.8125 - 1e-9,
        })
    return out


class RenderJobTests(unittest.TestCase):
    def test_one_job_per_take(self):
        takes = _takes((0, "intro", 0.0, 4.8125), (1, "verse", 4.8125, 9.625))
        jobs = render_jobs(takes)
        self.assertEqual(len(takes), len(jobs), f"denominador: {len(takes)} takes")

    def test_job_pairs_the_two_keyframes_that_bound_the_take(self):
        jobs = render_jobs(_takes((0, "intro", 0.0, 4.8125)))
        self.assertEqual("kf_000", jobs[0]["first"])
        self.assertEqual("kf_001", jobs[0]["last"])

    def test_job_uses_the_motion_prompt_not_the_keyframe_prompt(self):
        jobs = render_jobs(_takes((0, "intro", 0.0, 4.8125)))
        self.assertEqual("motion intro", jobs[0]["prompt"])

    def test_seeds_differ_between_takes(self):
        jobs = render_jobs(_takes((0, "a", 0.0, 4.8), (1, "b", 4.8, 9.6)))
        self.assertNotEqual(jobs[0]["seed"], jobs[1]["seed"])

    def test_no_takes_yield_no_jobs(self):
        self.assertEqual([], render_jobs([]))


class BuildGraphTests(unittest.TestCase):
    def _job(self, **over):
        job = {"prompt": "a scene", "negative": "blurry", "seed": 42,
               "frames": 81, "first": "kf_000.png", "last": "kf_001.png",
               "id": "take_000"}
        job.update(over)
        return job

    def test_every_marker_is_substituted_and_the_result_parses(self):
        g = build_graph(TEMPLATE, self._job())
        raw = json.dumps(g)
        for marker in ("%first%", "%last%", "%prompt%", "%negative%",
                       "%seed%", "%frames%"):
            self.assertNotIn(marker, raw, f"{marker} sobrou no grafo")
        self.assertEqual("kf_000.png", g["3"]["inputs"]["image"])
        self.assertEqual("kf_001.png", g["4"]["inputs"]["image"])
        self.assertIn("a scene", g["5"]["inputs"]["text"])
        self.assertEqual("blurry", g["6"]["inputs"]["text"])

    def test_seed_and_length_stay_numbers_not_strings(self):
        g = build_graph(TEMPLATE, self._job())
        self.assertIsInstance(g["7"]["inputs"]["seed"], int)
        self.assertIsInstance(g["8"]["inputs"]["length"], int)

    def test_quote_and_backslash_in_prompt_cannot_break_the_json(self):
        # Fronteira de confianca: motion_prompt vem de song.toml, texto livre.
        g = build_graph(TEMPLATE, self._job(prompt='he said "hi" \ and left'))
        self.assertIn('he said "hi" \ and left', g["5"]["inputs"]["text"])

    def test_newline_in_negative_cannot_break_the_json(self):
        g = build_graph(TEMPLATE, self._job(negative="line one\nline two"))
        self.assertEqual("line one\nline two", g["6"]["inputs"]["text"])

    def test_a_prompt_that_looks_like_a_marker_is_not_re_substituted(self):
        # Substituicao de uma passada so: %seed% digitado pelo autor fica literal.
        g = build_graph(TEMPLATE, self._job(prompt="%seed% on a boat"))
        self.assertIn("%seed% on a boat", g["5"]["inputs"]["text"])

    def test_filename_prefix_carries_a_nonce(self):
        # Armadilha do ComfyUI: grafo identico devolve execution_cached vazio.
        a = build_graph(TEMPLATE, self._job())["9"]["inputs"]["filename_prefix"]
        b = build_graph(TEMPLATE, self._job())["9"]["inputs"]["filename_prefix"]
        self.assertTrue(a.startswith("take_000"))
        self.assertNotEqual(a, b, "sem nonce o ComfyUI devolve cache vazio")

    def test_a_workflow_missing_a_marker_is_refused_by_name(self):
        broken = TEMPLATE.replace("%last%", "hardcoded.png")
        with self.assertRaises(ValueError) as ctx:
            build_graph(broken, self._job())
        self.assertIn("%last%", str(ctx.exception))


class SpliceOffsetTests(unittest.TestCase):
    # slot = (81-4)/16 = 4.8125 s; take gerado = 81/16 = 5.0625 s
    def test_uniform_takes_are_spaced_by_one_slot(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "a", 4.8125, 9.625),
                       (2, "a", 9.625, 14.4375))
        self.assertEqual([4.8125, 9.625], splice_offsets(takes))

    def test_one_offset_per_junction(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "a", 4.8125, 9.625),
                       (2, "a", 9.625, 14.4375))
        self.assertEqual(len(takes) - 1, len(splice_offsets(takes)),
                         f"denominador: {len(takes)} takes, {len(takes) - 1} emendas")

    def test_a_trimmed_take_shortens_the_offsets_that_follow_it(self):
        # A secao acaba em 7.0, antes do slot cheio: o take 1 e' trimmed e o
        # take 2 comeca no tempo absoluto dele, nao em 2 x slot.
        takes = _takes((0, "verse", 0.0, 4.8125), (1, "verse", 4.8125, 7.0),
                       (2, "chorus", 7.0, 11.8125))
        self.assertTrue(takes[1]["trimmed"], "premissa do teste: take 1 e' trimmed")
        self.assertEqual([4.8125, 7.0], splice_offsets(takes))

    def test_offsets_are_relative_to_the_first_take_not_to_zero(self):
        takes = _takes((0, "a", 12.0, 16.8125), (1, "a", 16.8125, 21.625))
        self.assertEqual([4.8125], splice_offsets(takes))

    def test_single_take_has_no_junction(self):
        self.assertEqual([], splice_offsets(_takes((0, "a", 0.0, 4.8125))))


class GapTests(unittest.TestCase):
    def test_contiguous_takes_report_no_gap(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "b", 4.8125, 9.625))
        self.assertEqual([], find_gaps(takes))

    def test_a_trimmed_take_is_not_a_gap(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "a", 4.8125, 7.0),
                       (2, "b", 7.0, 11.8125))
        self.assertEqual([], find_gaps(takes), "secao encurtada nao abre buraco")

    def test_an_instrumental_break_is_reported_with_seconds(self):
        # Secao b so comeca 3 s depois do fim da secao a: o take 0 nao tem
        # frames que cheguem ate la, e emendar em silencio desalinha a letra.
        takes = _takes((0, "a", 0.0, 4.8125), (1, "b", 7.8125, 12.625))
        gaps = find_gaps(takes)
        self.assertEqual(1, len(gaps), f"denominador: {len(takes) - 1} emendas")
        self.assertEqual(0, gaps[0]["after_idx"])
        self.assertAlmostEqual(3.0, gaps[0]["seconds"], places=6)


class ConcatFilterTests(unittest.TestCase):
    def test_one_xfade_per_junction(self):
        f = concat_filter([4.8125, 9.625], 0.25)
        self.assertEqual(2, f.count("xfade"), "denominador: 2 emendas")

    def test_every_offset_reaches_the_filter(self):
        f = concat_filter([4.8125, 9.625], 0.25)
        self.assertIn("offset=4.8125", f)
        self.assertIn("offset=9.625", f)
        self.assertIn("duration=0.25", f)

    def test_the_chain_is_wired_head_to_tail(self):
        f = concat_filter([4.8125, 9.625], 0.25)
        self.assertIn("[0:v][1:v]", f)
        self.assertIn("[2:v]", f)

    def test_a_single_take_needs_no_filter(self):
        self.assertEqual("", concat_filter([], 0.25))


def _make_mp4(path, frames, fps=16):
    """MP4 real, com a contagem de frames pedida. Nao e' mock: o ffprobe le."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=size=64x64:rate={fps}", "-frames:v", str(frames),
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "precisa de ffmpeg/ffprobe no PATH")
class VerifyTakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_take_with_the_expected_frame_count_is_accepted(self):
        mp4 = _make_mp4(self.dir / "ok.mp4", 81)
        self.assertIsNone(verify_take(mp4, 81))

    def test_a_short_take_is_refused_with_both_counts(self):
        # 80 frames em vez de 81: sozinho parece nada, mas envenena em
        # silencio todas as emendas seguintes.
        mp4 = _make_mp4(self.dir / "short.mp4", 80)
        reason = verify_take(mp4, 81)
        self.assertIsNotNone(reason, "take curto tem que ser recusado")
        self.assertIn("80", reason)
        self.assertIn("81", reason)

    def test_a_missing_file_is_refused(self):
        self.assertIsNotNone(verify_take(self.dir / "nao_existe.mp4", 81))

    def test_an_empty_file_is_refused(self):
        empty = self.dir / "empty.mp4"
        empty.write_bytes(b"")
        self.assertIsNotNone(verify_take(empty, 81))

    def test_a_file_that_is_not_video_is_refused(self):
        junk = self.dir / "junk.mp4"
        junk.write_bytes(b"not a video at all")
        self.assertIsNotNone(verify_take(junk, 81))


class FakeComfy(http.server.BaseHTTPRequestHandler):
    """ComfyUI de mentira, respostas de verdade: /view devolve MP4 que decodifica."""

    uploads: list = []
    prompts: list = []
    payload: bytes = b""

    def log_message(self, *a):  # silencio no output do teste
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/upload/image":
            m = re.search(rb'filename="([^"]+)"', raw)
            name = m.group(1).decode() if m else "unknown.png"
            type(self).uploads.append(name)
            self._json({"name": name, "subfolder": "", "type": "input"})
        elif self.path == "/prompt":
            type(self).prompts.append(json.loads(raw))
            self._json({"prompt_id": f"p{len(type(self).prompts)}"})
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path.startswith("/system_stats"):
            self._json({"system": {"comfyui_version": "fake"}})
        elif self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[-1]
            self._json({pid: {"outputs": {"9": {"gifs": [
                {"filename": f"{pid}.mp4", "subfolder": "", "type": "output"}]}}}})
        elif self.path.startswith("/view"):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(type(self).payload)))
            self.end_headers()
            self.wfile.write(type(self).payload)
        else:
            self.send_error(404)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "precisa de ffmpeg/ffprobe no PATH")
class RemoteRoundTripTests(unittest.TestCase):
    """O runner inteiro contra o fake: upload, submit, espera, download, prova."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.kf_dir = self.dir / "keyframes"
        self.kf_dir.mkdir()
        for i in range(3):
            (self.kf_dir / f"kf_{i:03d}.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")
        self.dest = self.dir / "takes"
        FakeComfy.uploads, FakeComfy.prompts = [], []
        FakeComfy.payload = _make_mp4(self.dir / "served.mp4", 81).read_bytes()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.jobs = render_jobs(_takes((0, "intro", 0.0, 4.8125),
                                       (1, "verse", 4.8125, 9.625)))

    def _run(self, **over):
        kw = {"template": TEMPLATE, "kf_dir": self.kf_dir, "dest": self.dest,
              "timeout": 30, "poll": 0.05}
        kw.update(over)
        return render_all(self.base, self.jobs, **kw)

    def test_every_take_lands_on_disk(self):
        ok, failures = self._run()
        self.assertEqual(2, ok, f"denominador: {len(self.jobs)} takes")
        self.assertEqual([], failures)
        self.assertTrue((self.dest / "take_000.mp4").exists())
        self.assertTrue((self.dest / "take_001.mp4").exists())

    def test_shared_keyframes_are_uploaded_once_each_not_twice_per_take(self):
        self._run()
        self.assertEqual(sorted(set(FakeComfy.uploads)), sorted(FakeComfy.uploads),
                         "keyframe subido duas vezes")
        self.assertEqual(3, len(FakeComfy.uploads),
                         f"denominador: {len(self.jobs)} takes -> {len(self.jobs) + 1} keyframes")

    def test_the_submitted_graph_carries_the_uploaded_names(self):
        self._run()
        first = FakeComfy.prompts[0]["prompt"]
        self.assertEqual("kf_000.png", first["3"]["inputs"]["image"])
        self.assertEqual("kf_001.png", first["4"]["inputs"]["image"])

    def test_a_take_already_on_disk_is_not_regenerated(self):
        self.dest.mkdir(parents=True, exist_ok=True)
        _make_mp4(self.dest / "take_000.mp4", 81)
        ok, failures = self._run()
        self.assertEqual(2, ok, "o take pronto conta como ok")
        self.assertEqual(1, len(FakeComfy.prompts),
                         "so o take que faltava foi submetido")

    def test_a_short_take_from_the_server_is_refused_not_written(self):
        FakeComfy.payload = _make_mp4(self.dir / "short.mp4", 60).read_bytes()
        ok, failures = self._run()
        self.assertEqual(0, ok)
        self.assertEqual(2, len(failures), f"denominador: {len(self.jobs)} takes")
        self.assertIn("60", failures[0])
        self.assertFalse((self.dest / "take_000.mp4").exists(),
                         "take reprovado nao pode ficar em disco fingindo de pronto")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "precisa de ffmpeg/ffprobe no PATH")
class MontageTests(unittest.TestCase):
    """A aritmetica fecha por outro caminho: a soma das partes tem que dar o
    total medido no arquivo montado, nao o que o filtro alegou."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _clips(self, n):
        return [_make_mp4(self.dir / f"take_{i:03d}.mp4", 81) for i in range(n)]

    def test_three_takes_of_81_frames_become_3x77_plus_4(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "a", 4.8125, 9.625),
                       (2, "a", 9.625, 14.4375))
        out = self.dir / "backdrop.mp4"
        self.assertIsNone(montage(self._clips(3), takes, out))
        self.assertEqual(3 * 77 + 4, probe_frames(out),
                         "denominador: 3 takes x 81 frames, 2 emendas de 4")

    def test_a_trimmed_take_shortens_the_montage_by_exactly_its_trim(self):
        # take 1 ocupa 2.1875 s em vez de 4.8125: o total cai para
        # (7.0 + 5.0625) x 16 = 193 frames.
        takes = _takes((0, "verse", 0.0, 4.8125), (1, "verse", 4.8125, 7.0),
                       (2, "chorus", 7.0, 11.8125))
        out = self.dir / "backdrop.mp4"
        self.assertIsNone(montage(self._clips(3), takes, out))
        self.assertEqual(193, probe_frames(out))

    def test_a_single_take_is_copied_whole(self):
        takes = _takes((0, "a", 0.0, 4.8125))
        out = self.dir / "backdrop.mp4"
        self.assertIsNone(montage(self._clips(1), takes, out))
        self.assertEqual(81, probe_frames(out))

    def test_an_instrumental_gap_refuses_the_montage_with_seconds(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "b", 7.8125, 12.625))
        out = self.dir / "backdrop.mp4"
        reason = montage(self._clips(2), takes, out)
        self.assertIsNotNone(reason, "buraco nao pode ser emendado em silencio")
        self.assertIn("3", reason)
        self.assertFalse(out.exists(), "nada de arquivo parcial fingindo de pronto")

    def test_a_missing_clip_refuses_the_montage(self):
        takes = _takes((0, "a", 0.0, 4.8125), (1, "a", 4.8125, 9.625))
        clips = self._clips(2)
        clips[1].unlink()
        self.assertIsNotNone(montage(clips, takes, self.dir / "backdrop.mp4"))
