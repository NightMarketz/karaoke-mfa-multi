# GPU Karaoke Spike (Tier 2)

Proves the **ceiling**: one real lyric line rendered as GPU text (SDF) with
spring physics + a real postprocessing **bloom driven by the measured vocal
envelope**, exported to a real **MP4** via Remotion (headless Chrome + ffmpeg).
Same data the ASS pipeline uses — so you can compare motion side by side.

## Run

> **Windows gotcha (this machine):** do NOT `npm install`/render inside this
> OneDrive-synced tree. OneDrive dehydrates `node_modules` (fake `EFTYPE` /
> `MODULE_NOT_FOUND`) and the deep path blows past MAX_PATH=260 so native
> `.exe` spawns fail with `ENOENT` even though the file exists. Copy the app to
> a **short local path** and run there.

```bash
# 1) feed it a real job (writes src/spike_data.json + public/segment.wav + public/font.ttf)
python spike/extract_spike_data.py --job-dir jobs/202605290001

# 2) copy to a short, non-OneDrive path
robocopy spike\gpu-karaoke C:\rk /E /XD node_modules out

# 3) install + render there
cd /d C:\rk
npm install
# if npm skips the .bin shims, call the CLI directly:
node node_modules/@remotion/cli/remotion-cli.js render src/index.ts KaraokeGpu C:/rk/out/karaoke_gpu.mp4 --gl=angle
#   add --browser-executable="<ms-playwright chrome-headless-shell.exe>" if Remotion's shell download 404s/ENOENTs

# live editor (scrub the motion):
node node_modules/@remotion/cli/remotion-cli.js studio src/index.ts
```

Verified output: `1920×1080 h264 + aac, ~5.5s, 1.6 MB`. See `out/frame_*.png`.

Two compositions live here:
- **`KaraokeGpu`** — the single-line spike (uses `src/spike_data.json`).
- **`KaraokeSong`** — the full-song composition the pipeline stage renders
  (uses `src/song_data.json`, sequences every lyric line on one timeline).

## Pipeline stage (`s06b_render_gpu`)

This app is productized as an **optional renderer** that replaces
`s06_generate_ass` + `s07_output`. Turn it on in `pipeline.toml`:

```toml
[render]
engine = "gpu"        # "ass" (default) | "gpu"

[render_gpu]
work_dir = "C:/rk"    # short, non-OneDrive path (staged + rendered here)
browser_executable = ""   # optional chrome-headless-shell.exe override
timeout_s = 3600
```

The runner then swaps the ASS tail for a single `rendering_gpu` stage. Run it
directly for one job (the stage stages the app to `work_dir`, renders the full
song, and copies the MP4 back):

```bash
python scripts/s06b_render_gpu.py --job-dir jobs/<id>              # full song
python scripts/s06b_render_gpu.py --job-dir jobs/<id> --max-seconds 20   # smoke slice
python scripts/s06b_render_gpu.py --job-dir jobs/<id> --prepare-only     # payload only
```

Output: `jobs/<id>/output_gpu.mp4` (+ manifest). Verified end-to-end on
job `202605290001` (20 s slice → 2 lines, 600 frames, ~73 s render).
Full-song renders take minutes — it's a headless Chromium+ffmpeg render.

## Finding & opening the rendered MP4 (why it keeps "disappearing")

The output is **not** where you're probably looking. Three traps, and the fix:

1. **It's in the MAIN checkout, not the worktree.** `jobs/` is gitignored, so a
   git *worktree* (`.claude/worktrees/…`) has **no `jobs/` folder**. The file is
   always under the real project:
   `C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\jobs\<id>\output_gpu.mp4`
2. **`cmd /c start "" "<path>"` is unreliable here** — the path has spaces and
   lives under OneDrive, so the empty-title `start` quoting often opens a stray
   cmd window instead of the video. Use PowerShell, which handles it:
   ```bash
   powershell.exe -NoProfile -Command "Start-Process 'C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\jobs\202605290001\output_gpu.mp4'"
   ```
   Or just paste that path into Explorer's address bar and press Enter.
3. **The player may open *behind* the active window** — check the taskbar before
   assuming it didn't launch. (Also: make sure `.mp4` has a default app set —
   Settings → Apps → Default apps → `.mp4`.)

To stop losing it, drop a copy somewhere obvious after a render:
```bash
cp "jobs/<id>/output_gpu.mp4" ~/Desktop/karaoke_gpu.mp4     # from the main checkout
```

## What it demonstrates (vs libass/ASS)

- **SDF text on the GPU** — crisp at any scale, real geometry per syllable.
- **Spring physics** assemble/dissolve-in per syllable (Remotion `spring()`).
- **Audio-reactive bloom** — glow intensity = `0.6 + vocalEnvelope * 3.0`, so
  the line literally glows louder when the vocal is louder. libass can't do this.
- **Same source of truth** — preview and MP4 come from the same React component.

## Extended-note (sustain) identification — how it works & known problems

The Guitar-Hero hold bar (`SustainBars` in `src/KaraokeGpu.tsx`) needs to know
which syllables are "held". **How it decides today (naive):**

- A syllable is "extended" iff its **symbolic duration** `end - start >= SUSTAIN_MIN`
  (0.45 s). That duration comes straight from `analysis.json` (s04 HubertFA
  phonemes → s05 syllables), passed through unchanged by `s06b_render_gpu`.
- Bar **length** ∝ that duration; the fill **consumes** it linearly over
  `[start, end]`; only the **head glow** uses a real audio signal (the per-frame
  vocal RMS `envelope`).

**Why that's wrong (the "clear problems"):**

1. **Symbolic duration ≠ acoustic sustain.** Forced alignment snaps the syllable
   end to a phoneme/word boundary, so it under- or over-shoots the real held
   tail. The pipeline *already knows this*: `scripts/review_wizard/timing_layers.py`
   computes `possible_lost_tail`, **`unwritten_interline_melisma`**, and
   `false_long_tail`, and `s06_generate_ass` applies
   `apply_audio_backed_tail_extensions`. **`s06b` ignores all of it** and uses raw
   durations — so a clipped melisma → bar too short, a `false_long_tail` → phantom
   bar over silence.
2. **Absorbed gaps inflate duration.** Trailing silence/instrumental folded into a
   syllable window makes `dur > 0.45` with no real hold → phantom bar.
3. **0.45 s is a blind constant** — unrelated to tempo; misses short real sustains,
   flags long-but-unheld syllables.
4. **No pitch → melisma looks identical to a steady vowel.** We only have duration
   + amplitude. A 4 s run of notes and a 4 s flat "aaah" render the same. True GH
   shows pitch; we don't.
5. **Length (symbolic) and head glow (RMS envelope) can disagree** — head goes dark
   while the bar keeps sliding, or glows past the bar end. No reconciliation.
6. **Last-syllable bias** — aligners dump leftover line time into the final
   syllable, over-flagging it as "extended".

**How we *should* do it (fix path, reusing what exists):**

- **[DONE]** Trim `[start, end]` to the **voiced span** using the `envelope` we
  already have per frame — `voicedSpan()` in `KaraokeGpu.tsx` takes the first→last
  frame where `env > SUSTAIN_ENV_THR` (0.1) inside the window; bar length + fill +
  the `SUSTAIN_MIN` test all use that trimmed span. A syllable with **no voiced
  audio → no bar** (kills `false_long_tail` phantoms); the bar now starts at the
  real vocal attack, not the aligner's boundary. Still per-renderer & threshold is
  fixed — the deeper items below remain.
- Better: in `s06b_render_gpu.build_song_payload`, feed syllable ends through
  `timing_layers.build_audio_backed_timing` / `apply_audio_backed_tail_extensions`
  (same functions `s06` uses) so the GPU and ASS paths agree on tails/melismas.
- **[DONE]** **Tail extension.** `voicedSpan()` now extends the hold PAST the
  aligned syllable end (through a held note, stopping at a real silence gap, capped
  by the next syllable / `MAX_TAIL`). This recovers melismas the aligner clipped to
  ~0 — e.g. "snap" @70.7 s is aligned **0.18 s** but actually held **~5.3 s**; before
  this it got no bar. `lineTailEnd()` also keeps the whole line (text + bar) on
  screen for the extended hold. Renderer-side approximation of the pipeline's
  `apply_audio_backed_tail_extensions`.
- Real melisma needs an **f0/pitch track** off `vocals.wav` → the bar could step
  with pitch (a genuine note lane). Bigger lift; future.
- Make the threshold **adaptive** (median syllable duration / tempo) instead of a
  fixed 0.45 s.

Until then the bar is an *approximate* sustain cue, not ground truth.

**Anchoring:** the hold bar is **centered on screen** (not under the glyph). A long
melisma on a right-side word (e.g. "snap" 6.6 s in *About to snap*) would otherwise
run its 1500 px bar off the right edge and the head would vanish mid-hold. Centered
+ capped (`BAR_MAX`) keeps any-length hold fully visible; concurrent holds stack
vertically. Trade-off: the bar reads as "current line's held note", not tied to the
exact word x.

## Knobs / next steps

- `FS`, `WAIT`, `SUNG` in `src/KaraokeGpu.tsx` — size and palette.
- Bloom `intensity`/`luminanceThreshold` — glow character.
- **Per-glyph shader dissolve** (DONE): fbm-noise threshold reveal + lit ember
  frontier (`DISSOLVE_FRAG` in `KaraokeGpu.tsx`) + additive spark burst on each
  syllable's attack. Tune `uEdge` (frontier width) and the ember colour there.
- Next: directional dissolve tracking the `\kf` sweep; MSDF mesh extrusion;
  per-section effect presets (verse/chorus) mirroring the ASS style presets.
- If the MP4 is **black**: set `Config.setChromiumOpenGlRenderer('swangle')` in
  `remotion.config.ts` (software GL for machines without a headless GPU).
```
