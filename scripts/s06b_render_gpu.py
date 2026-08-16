r"""
s06b_render_gpu.py — GPU karaoke renderer (Remotion + three.js), optional
drop-in alternative to s06_generate_ass + s07_output.

Reads the same analysis.json the ASS path uses and renders a full-song GPU
karaoke MP4 (per-glyph shader dissolve, ember frontier, audio-reactive bloom,
spark bursts) straight to job_dir/output_gpu.mp4 — no ASS/libass involved.

Pipeline plug: selected by `[render] engine = "gpu"` in pipeline.toml (see
pipeline_runner.build_stage_plan). The ASS path stays the default.

Environment note (Windows/this box): the Remotion app has native .exe deps
(Rust compositor, chrome-headless-shell). Those fail to spawn from the
OneDrive-synced project tree (dehydration) or from a path >260 chars (MAX_PATH).
So the app is staged to a short local work dir (default C:/rk) and rendered
there, then the MP4 is copied back into the job. Configure via [render_gpu].

Usage:
    python scripts/s06b_render_gpu.py --job-dir jobs/202605290001
    python scripts/s06b_render_gpu.py --job-dir jobs/my-job --max-seconds 20   # smoke
    python scripts/s06b_render_gpu.py --job-dir jobs/my-job --prepare-only     # write payload only

Reads:  jobs/{id}/analysis.json, instrumental.wav (soundtrack), vocals.wav (envelope)
Writes: jobs/{id}/output_gpu.mp4 (+ manifest)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from scripts.common.observability import record_artifact, write_event
from scripts.common.provenance import file_sha256, write_manifest

logger = logging.getLogger(__name__)

FPS = 30
WIDTH, HEIGHT = 1920, 1080
DEFAULT_WORK_DIR = "C:/rk"
DEFAULT_APP_DIR = Path(__file__).resolve().parent.parent / "spike" / "gpu-karaoke"
# soundtrack preference: instrumental first (karaoke), then any mix, then vocals
SOUNDTRACK_CANDIDATES = ("instrumental.wav", "no_vocals.wav", "accompaniment.wav", "input.wav", "vocals.wav")
FONT_CANDIDATES = ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf")


def _render_gpu_cfg(path: str = "pipeline.toml") -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    section = data.get("render_gpu", {})
    return section if isinstance(section, dict) else {}


def _units_from_word(word: dict) -> list[dict]:
    """One karaoke unit per syllable if the job carries them, else the word."""
    syls = word.get("syllables")
    if isinstance(syls, list) and syls:
        out = []
        for s in syls:
            txt = str(s.get("text") or s.get("syllable") or "").strip()
            if txt and s.get("start") is not None and s.get("end") is not None:
                out.append({"text": txt, "start": float(s["start"]), "end": float(s["end"])})
        if out:
            return out
    return [{"text": str(word.get("word", "")).strip(),
             "start": float(word["start"]), "end": float(word["end"])}]


def _vocal_envelope(vocals: Path, duration_frames: int) -> list[float]:
    """Per-frame RMS envelope of the vocal stem, normalized to [0, 1]."""
    info = sf.info(str(vocals))
    sr = info.samplerate
    seg, _ = sf.read(str(vocals), always_2d=True)
    mono = seg.mean(axis=1)
    hop = sr / FPS
    win = int(round(hop))
    env = np.zeros(duration_frames, dtype=np.float64)
    for i in range(duration_frames):
        a = int(i * hop)
        b = min(len(mono), a + win)
        if b > a:
            env[i] = np.sqrt(np.mean(mono[a:b] ** 2))
    env = env / (env.max() + 1e-9)
    return [round(float(x), 4) for x in env]


def build_song_payload(job_dir: Path, max_seconds: float | None) -> tuple[dict, Path]:
    """Build the Remotion song_data.json payload from the job + pick soundtrack."""
    analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
    raw_lines = analysis.get("lines", [])
    if not raw_lines:
        raise ValueError("analysis.json has no lines")

    soundtrack = next((job_dir / n for n in SOUNDTRACK_CANDIDATES if (job_dir / n).exists()), None)
    if soundtrack is None:
        raise FileNotFoundError(f"no soundtrack found in {job_dir} (looked for {SOUNDTRACK_CANDIDATES})")
    info = sf.info(str(soundtrack))
    track_s = info.frames / info.samplerate
    if max_seconds is not None:
        track_s = min(track_s, float(max_seconds))
    duration_frames = max(1, int(round(track_s * FPS)))

    lines: list[dict] = []
    charset: set[str] = set(" '.,!?-")
    for ln in raw_lines:
        start, end = float(ln.get("start", 0)), float(ln.get("end", 0))
        if end <= start or start >= track_s:
            continue  # skip inverted / out-of-window lines
        syllables: list[dict] = []
        for w in ln.get("words", []):
            for u in _units_from_word(w):
                syllables.append({
                    "text": u["text"],
                    "start": round(u["start"], 4),
                    "end": round(max(u["end"], u["start"] + 0.08), 4),
                })
                charset.update(u["text"])
        if syllables:
            lines.append({"winStart": round(start, 4), "winEnd": round(min(end, track_s), 4),
                          "syllables": syllables})
    if not lines:
        raise ValueError("no renderable lines after filtering")

    payload = {
        "fps": FPS, "width": WIDTH, "height": HEIGHT,
        "durationInFrames": duration_frames,
        "job": job_dir.name,
        "audio": "song.wav",
        "chars": "".join(sorted(charset)),
        "lines": lines,
        "envelope": _vocal_envelope(job_dir / "vocals.wav", duration_frames)
        if (job_dir / "vocals.wav").exists() else [0.0] * duration_frames,
    }
    # self-check: timeline sanity
    assert len(payload["envelope"]) == duration_frames, "envelope/frame mismatch"
    assert all(s["end"] > s["start"] for ln in lines for s in ln["syllables"]), "bad syllable timing"
    return payload, soundtrack


def write_app_assets(app_dir: Path, payload: dict, soundtrack: Path,
                     vocals_path: Path | None = None, vocal_gain: float = 1.0) -> None:
    (app_dir / "src").mkdir(parents=True, exist_ok=True)
    (app_dir / "public").mkdir(parents=True, exist_ok=True)
    (app_dir / "src" / "song_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # soundtrack → public/song.wav; optionally mix the vocal stem back in (guide
    # vocal) so the render can be checked against where the singer actually sings.
    seg, sr = sf.read(str(soundtrack), always_2d=True)
    if vocals_path is not None and vocals_path.exists():
        voc, _ = sf.read(str(vocals_path), always_2d=True)
        n = min(len(seg), len(voc))
        seg = seg[:n] + voc[:n] * vocal_gain
        peak = float(np.max(np.abs(seg))) if len(seg) else 1.0
        if peak > 1.0:
            seg = seg / peak                       # prevent clipping from the sum
    max_frames = int(payload["durationInFrames"] / FPS * sr) + sr
    sf.write(str(app_dir / "public" / "song.wav"), seg[:max_frames], sr)
    font = next((Path(p) for p in FONT_CANDIDATES if Path(p).exists()), None)
    if font:
        shutil.copy(font, app_dir / "public" / "font.ttf")


def stage_to_workdir(app_dir: Path, work_dir: Path) -> None:
    """Copy app source into a short local work dir (node_modules/out preserved)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "tsconfig.json", "remotion.config.ts"):
        if (app_dir / name).exists():
            shutil.copy(app_dir / name, work_dir / name)
    for sub in ("src", "public"):
        dst = work_dir / sub
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(app_dir / sub, dst)
    (work_dir / "out").mkdir(exist_ok=True)


def ensure_deps(work_dir: Path) -> None:
    cli = work_dir / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    if cli.exists():
        return
    logger.info("Installing Remotion deps in %s (first run)…", work_dir)
    res = subprocess.run(["npm", "install", "--no-audit", "--no-fund"],
                         cwd=str(work_dir), capture_output=True, text=True, shell=True)
    if res.returncode != 0 or not cli.exists():
        raise RuntimeError(f"npm install failed in {work_dir}: {res.stderr[-800:]}")


def render(work_dir: Path, out_mp4: Path, browser_exe: str, timeout_s: int,
           concurrency: int | None = None, crf: int | None = None) -> None:
    cli = work_dir / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    cmd = ["node", str(cli), "render", "src/index.ts", "KaraokeSong", str(out_mp4),
           "--gl=angle", f"--timeout={min(60000, timeout_s * 1000)}"]
    if concurrency and concurrency > 0:
        cmd.append(f"--concurrency={concurrency}")  # parallel frame renderers — the real speed lever
    if crf is not None:
        cmd.append(f"--crf={crf}")
    if browser_exe:
        cmd.append(f"--browser-executable={browser_exe}")
    res = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout_s)
    if res.returncode != 0 or not out_mp4.exists():
        tail = (res.stderr or res.stdout or "")[-1200:]
        raise RuntimeError(f"remotion render failed (rc={res.returncode}): {tail}")


def _amf_quality_args(vcodec: str, quality: int) -> list[str]:
    """Mirror s07: AMF uses CQP (it silently ignores -crf); others use CRF."""
    q = str(quality)
    if vcodec == "h264_amf":
        return ["-rc", "cqp", "-qp_i", q, "-qp_p", q, "-qp_b", q]
    if vcodec == "hevc_amf":
        return ["-rc", "cqp", "-qp_i", q, "-qp_p", q]
    return ["-crf", q]


def reencode(src_mp4: Path, dst_mp4: Path, vcodec: str, quality: int, timeout_s: int) -> None:
    """Final encode with the system ffmpeg (e.g. h264_amf), matching the s07 pipeline.

    ponytail: rendering (browser+readback), not encoding, dominates wall-clock — this
    pass is for output consistency/size with the ASS path, not render speedup.
    """
    cmd = ["ffmpeg", "-y", "-i", str(src_mp4), "-c:v", vcodec,
           *_amf_quality_args(vcodec, quality), "-pix_fmt", "yuv420p",
           "-c:a", "copy", str(dst_mp4)]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout_s)
    if res.returncode != 0 or not dst_mp4.exists():
        tail = (res.stderr or res.stdout or "")[-1200:]
        raise RuntimeError(f"ffmpeg {vcodec} re-encode failed (rc={res.returncode}): {tail}")


def _update_status(job_dir: Path, stage: str, progress: int, error: str = "") -> None:
    path = job_dir / "status.json"
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
        if not isinstance(existing, dict):
            existing = {}
    existing.update({"stage": stage, "progress": progress, "error": error, "updated_at": time.time()})
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def main() -> int:
    cfg = _render_gpu_cfg()
    ap = argparse.ArgumentParser(description="Stage 06b — GPU karaoke render (Remotion).",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--job-dir", required=True, type=Path)
    ap.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    ap.add_argument("--work-dir", type=Path, default=Path(str(cfg.get("work_dir", DEFAULT_WORK_DIR))))
    ap.add_argument("--browser-executable", default=str(cfg.get("browser_executable", "")))
    ap.add_argument("--timeout-s", type=int, default=int(cfg.get("timeout_s", 3600)))
    ap.add_argument("--concurrency", type=int, default=int(cfg.get("concurrency", 0)),
                    help="parallel frame renderers (0=Remotion auto). Biggest wall-clock lever.")
    ap.add_argument("--crf", type=int, default=cfg.get("crf", None),
                    help="Remotion h264 CRF (lower=better; Remotion default ~18).")
    ap.add_argument("--amf", dest="amf", action="store_true", default=bool(cfg.get("amf_encode", False)),
                    help="final re-encode with the system ffmpeg hardware encoder (AMF).")
    ap.add_argument("--no-amf", dest="amf", action="store_false",
                    help="skip the AMF re-encode; keep Remotion's h264 output.")
    ap.add_argument("--amf-vcodec", default=str(cfg.get("amf_vcodec", "h264_amf")))
    ap.add_argument("--amf-quality", type=int, default=int(cfg.get("amf_quality", 23)),
                    help="AMF CQP value 0-51 (lower=better).")
    ap.add_argument("--with-vocals", action="store_true", default=bool(cfg.get("include_vocals", False)),
                    help="mix the vocal stem into the soundtrack (guide vocal, to verify sync).")
    ap.add_argument("--vocal-gain", type=float, default=float(cfg.get("vocal_gain", 1.0)),
                    help="gain applied to the mixed-in vocal stem.")
    ap.add_argument("--max-seconds", type=float, default=None, help="cap render length (smoke test)")
    ap.add_argument("--prepare-only", action="store_true", help="write payload/assets, skip render")
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()

    job_dir: Path = args.job_dir.resolve()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if job_dir.exists():
        handlers.append(logging.FileHandler(job_dir / "pipeline.log", mode="a"))
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="%(asctime)s [%(levelname)s] %(message)s", force=True, handlers=handlers)

    if not (job_dir / "analysis.json").exists():
        logger.error("analysis.json missing in %s — run Stage 05 first.", job_dir)
        return 1

    write_event(job_dir, "stage06b.started", "rendering_gpu",
                details={"work_dir": str(args.work_dir), "max_seconds": args.max_seconds})
    _update_status(job_dir, "rendering_gpu", 0)
    t0 = time.perf_counter()

    try:
        payload, soundtrack = build_song_payload(job_dir, args.max_seconds)
        app_dir = args.app_dir.resolve()
        vocals = job_dir / "vocals.wav"
        mix_vocals = args.with_vocals and vocals.exists()
        write_app_assets(app_dir, payload, soundtrack,
                         vocals_path=vocals if mix_vocals else None, vocal_gain=args.vocal_gain)
        logger.info("Payload: %d lines, %d frames (%.1fs), soundtrack=%s%s",
                    len(payload["lines"]), payload["durationInFrames"],
                    payload["durationInFrames"] / FPS, soundtrack.name,
                    f" + vocals(gain={args.vocal_gain})" if mix_vocals else "")
        write_event(job_dir, "stage06b.payload_built", "rendering_gpu",
                    details={"lines": len(payload["lines"]),
                             "duration_frames": payload["durationInFrames"],
                             "soundtrack": soundtrack.name})
    except Exception as exc:
        logger.error("payload build failed: %s", exc)
        write_event(job_dir, "stage06b.failed", "rendering_gpu", level="error", message=str(exc))
        _update_status(job_dir, "failed", 0, str(exc))
        return 1

    if args.prepare_only:
        logger.info("prepare-only: wrote song_data.json + song.wav into %s", app_dir)
        return 0

    work_dir: Path = args.work_dir.resolve()
    out_mp4 = work_dir / "out" / "song.mp4"
    encoder = "remotion_h264"
    try:
        stage_to_workdir(app_dir, work_dir)
        ensure_deps(work_dir)
        _update_status(job_dir, "rendering_gpu", 30)
        logger.info("Rendering (full GPU render - expect minutes for a full song). concurrency=%s crf=%s",
                    args.concurrency or "auto", args.crf if args.crf is not None else "default")
        render(work_dir, out_mp4, args.browser_executable, args.timeout_s,
               concurrency=args.concurrency, crf=args.crf)
        src_for_final = out_mp4
        if args.amf:
            _update_status(job_dir, "rendering_gpu", 80)
            amf_mp4 = work_dir / "out" / "song_amf.mp4"
            logger.info("Re-encoding with %s (CQP %d)...", args.amf_vcodec, args.amf_quality)
            reencode(out_mp4, amf_mp4, args.amf_vcodec, args.amf_quality, args.timeout_s)
            src_for_final = amf_mp4
            encoder = args.amf_vcodec
    except Exception as exc:
        logger.error("render failed: %s", exc)
        write_event(job_dir, "stage06b.failed", "rendering_gpu", level="error", message=str(exc)[:1200])
        _update_status(job_dir, "failed", 30, str(exc)[:400])
        return 1

    final = job_dir / "output_gpu.mp4"
    shutil.copy(src_for_final, final)
    assert final.exists() and final.stat().st_size > 100_000, "output MP4 missing or too small"

    manifest_path = write_manifest(
        job_dir / "output_gpu.mp4.manifest.json",
        {
            "stage": "stage06b",
            "renderer": "remotion_three_gpu",
            "composition": "KaraokeSong",
            "encoder": encoder,
            "concurrency": args.concurrency or "auto",
            "inputs": {"analysis.json": {"path": "analysis.json",
                                         "sha256": file_sha256(job_dir / "analysis.json")}},
            "outputs": {"output_gpu.mp4": {"path": "output_gpu.mp4"}},
            "metrics": {"lines": len(payload["lines"]),
                        "duration_frames": payload["durationInFrames"],
                        "render_seconds": round(time.perf_counter() - t0, 1)},
        },
        output_paths={"output_gpu.mp4": final},
    )
    details = record_artifact(job_dir, "rendering_gpu", final)
    _update_status(job_dir, "rendering_gpu", 100)
    write_event(job_dir, "stage06b.completed", "rendering_gpu",
                details={"path": str(final), "size_bytes": details["size_bytes"],
                         "manifest_sha256": file_sha256(manifest_path),
                         "render_seconds": round(time.perf_counter() - t0, 1)})
    logger.info("Stage 06b complete -> %s (%.1f KB, %.0fs)",
                final.name, final.stat().st_size / 1e3, time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
