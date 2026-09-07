#!/usr/bin/env python
r"""
extract_spike_data.py — Feed one real karaoke line into the GPU render spike.

Pulls a single lyric line from a job's analysis.json, computes a per-frame
vocal RMS envelope from vocals.wav, trims that audio window, and copies a
system font. Everything lands inside the Remotion app so it is self-contained.

Outputs (into spike/gpu-karaoke/):
    src/spike_data.json     line + syllables (window-relative s) + envelope[frame]
    public/segment.wav      trimmed vocal audio for the MP4 soundtrack
    public/font.ttf         font used by the MSDF text

Usage:
    python spike/extract_spike_data.py --job-dir jobs/202605290001
    python spike/extract_spike_data.py --job-dir jobs/202605290001 --line-index 12

ponytail: word-level units; uses word["syllables"] if the job carries them.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf

FPS = 30
WIDTH, HEIGHT = 1920, 1080
PAD_BEFORE = 0.4   # s of lead-in before the line
PAD_AFTER = 0.6    # s of tail after the line
FONT_CANDIDATES = [
    r"C:/Windows/Fonts/segoeuib.ttf",
    r"C:/Windows/Fonts/arialbd.ttf",
    r"C:/Windows/Fonts/arial.ttf",
]


def _units_from_word(word: dict) -> list[dict]:
    """One karaoke unit per syllable if present, else the whole word."""
    syls = word.get("syllables")
    if isinstance(syls, list) and syls:
        out = []
        for s in syls:
            t = str(s.get("text") or s.get("syllable") or "").strip()
            if t and s.get("start") is not None and s.get("end") is not None:
                out.append({"text": t, "start": float(s["start"]), "end": float(s["end"])})
        if out:
            return out
    return [{"text": str(word["word"]).strip(),
             "start": float(word["start"]), "end": float(word["end"])}]


def _pick_line(lines: list[dict], forced: int | None) -> tuple[int, dict]:
    if forced is not None:
        return forced, lines[forced]
    best = None
    for i, ln in enumerate(lines):
        words = ln.get("words") or []
        dur = float(ln.get("end", 0)) - float(ln.get("start", 0))
        text = str(ln.get("text", ""))
        if not (3 <= len(words) <= 7 and 1.5 <= dur <= 5.0 and len(text) <= 40):
            continue
        # prefer clear, well-spaced timing (higher mean word duration)
        mean_word = np.mean([float(w["end"]) - float(w["start"]) for w in words])
        score = mean_word
        if best is None or score > best[0]:
            best = (score, i, ln)
    if best is None:
        # fallback: first line with >= 3 words
        for i, ln in enumerate(lines):
            if len(ln.get("words") or []) >= 3:
                return i, ln
        return 0, lines[0]
    return best[1], best[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job-dir", required=True, type=Path)
    ap.add_argument("--line-index", type=int, default=None)
    ap.add_argument("--app-dir", type=Path, default=Path(__file__).resolve().parent / "gpu-karaoke")
    args = ap.parse_args()

    job = args.job_dir.resolve()
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    lines = analysis.get("lines", [])
    if not lines:
        print("no lines in analysis.json"); return 1

    idx, line = _pick_line(lines, args.line_index)
    l_start, l_end = float(line["start"]), float(line["end"])
    text = str(line.get("text", "")).strip()
    print(f"line #{idx}: '{text}'  [{l_start:.2f}..{l_end:.2f}]  style={line.get('style')}")

    units: list[dict] = []
    for w in line.get("words", []):
        units.extend(_units_from_word(w))

    # ── audio window ────────────────────────────────────────────────────────
    w0 = max(0.0, l_start - PAD_BEFORE)
    w1 = l_end + PAD_AFTER
    voc = job / "vocals.wav"
    info = sf.info(str(voc))
    sr = info.samplerate
    seg, _ = sf.read(str(voc), start=int(w0 * sr),
                     stop=min(info.frames, int(w1 * sr)), always_2d=True)
    w1 = w0 + seg.shape[0] / sr  # clamp to real length
    duration_frames = max(1, int(round((w1 - w0) * FPS)))

    # per-frame RMS envelope, normalized to [0, 1]
    mono = seg.mean(axis=1)
    hop = sr / FPS
    win = int(round(hop))
    env = np.zeros(duration_frames, dtype=np.float64)
    for i in range(duration_frames):
        a = int(i * hop); b = min(len(mono), a + win)
        if b > a:
            env[i] = np.sqrt(np.mean(mono[a:b] ** 2))
    env = env / (env.max() + 1e-9)

    # ── write app assets ────────────────────────────────────────────────────
    app = args.app_dir.resolve()
    (app / "src").mkdir(parents=True, exist_ok=True)
    (app / "public").mkdir(parents=True, exist_ok=True)

    sf.write(str(app / "public" / "segment.wav"), seg, sr)

    font_src = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if font_src:
        shutil.copy(font_src, app / "public" / "font.ttf")
        print(f"font: {font_src}")
    else:
        print("WARNING: no system font found; set font in KaraokeGpu.tsx manually")

    data = {
        "fps": FPS, "width": WIDTH, "height": HEIGHT,
        "durationInFrames": duration_frames,
        "job": job.name, "lineIndex": idx,
        "text": text,
        "windowStart": w0,
        # syllable times are relative to the window start (seconds)
        "syllables": [
            {"text": u["text"],
             "start": round(u["start"] - w0, 4),
             "end": round(max(u["end"], u["start"] + 0.08) - w0, 4)}
            for u in units
        ],
        "envelope": [round(float(x), 4) for x in env],
    }
    (app / "src" / "spike_data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # self-check: envelope length matches frames, syllables cover the line
    assert len(data["envelope"]) == duration_frames, "envelope/frame mismatch"
    assert data["syllables"], "no syllables extracted"
    assert all(s["end"] > s["start"] for s in data["syllables"]), "bad syllable timing"
    print(f"OK  {len(units)} syllables, {duration_frames} frames "
          f"({duration_frames/FPS:.2f}s), env peak frame "
          f"{int(np.argmax(env))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
