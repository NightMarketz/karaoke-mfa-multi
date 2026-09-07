import {useEffect, useMemo, useState} from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {ThreeCanvas} from '@remotion/three';
import {EffectComposer, Bloom} from '@react-three/postprocessing';
import {preloadFont} from 'troika-three-text';
import {
  DissolveFX,
  FONT,
  LineGlyphs,
  Placed,
  REVEAL_LEAD,
  Colors,
  DEFAULT_COLORS,
  SUSTAIN_ENV_THR,
  SustainBars,
  Syl,
  fillRevealTexture,
  layout,
  lineTailEnd,
  makeSparks,
  newRevealTexture,
} from './KaraokeGpu';
import song from './song_data.json';

// Full-song composition: the same GPU dissolve scene as the single-line spike,
// but every lyric line is placed on one timeline. A single ThreeCanvas draws
// whichever line(s) are active at the current frame (lyrics are sequential, so
// usually exactly one), dissolving in on its window and fading out at the end.
// This is what s06b_render_gpu renders as output_gpu.mp4.

const FADE_IN = 0.3;   // s
const FADE_OUT = 0.4;  // s

type Line = {winStart: number; winEnd: number; syllables: Syl[]; style?: string};

// s06b writes one entry per style key of the chosen preset. Older payloads have
// no palette at all, so the spike's own colours stay as the fallback.
const PALETTE: Record<string, Colors> = (song as {palette?: Record<string, Colors>}).palette ?? {};
const colorsFor = (style?: string): Colors => PALETTE[style ?? 'verse'] ?? DEFAULT_COLORS;

const SongScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const t = frame / fps;
  const env = (song.envelope as number[])[Math.min(frame, song.envelope.length - 1)] ?? 0;
  const groupScale = 1 + env * 0.04;

  const lines = song.lines as Line[];
  const placedPerLine = useMemo(() => lines.map((l) => layout(l.syllables)), []);
  // effective line end = max(symbolic winEnd, voiced-tail end) — keeps a line up
  // while a clipped-alignment melisma is still held (e.g. "snap" @70.7s → ~76s).
  const effEnds = useMemo(
    () => lines.map((l, i) => Math.max(l.winEnd, lineTailEnd(placedPerLine[i], song.envelope as number[], fps, SUSTAIN_ENV_THR))),
    [placedPerLine, fps],
  );
  const revealTex = useMemo(() => newRevealTexture(), []);
  // one spark cloud for the whole song (per-vertex attack + world-x)
  const sparks = useMemo(() => makeSparks(placedPerLine.flat()), [placedPerLine]);

  // ONE line at a time. Consecutive lyric lines are (mostly) back-to-back, so a shared
  // centered layout meant the next line's dissolve-in appeared ON TOP of the previous
  // line still fading out → "encavalado". Tile the timeline into non-overlapping display
  // windows: each line owns [s, e]; the next line can't appear until the previous window
  // ends (a line hands off exactly when the next one starts singing). Sing/highlight and
  // per-syllable reveal timing are UNTOUCHED — only the visibility (fade) window changes.
  // Where there's a real gap the full dissolve-in lead survives; where lines are
  // back-to-back it becomes a clean baton pass with no overlap.
  const dispWins = useMemo(() => {
    const LEAD = REVEAL_LEAD + FADE_IN;                 // pre-appear (dissolve-in) budget
    const wins: {s: number; e: number}[] = [];
    let prevEnd = -Infinity;
    for (let i = 0; i < lines.length; i++) {
      const boundary = i + 1 < lines.length ? lines[i + 1].winStart : Infinity; // next takes over when it sings
      const s = Math.max(lines[i].winStart - LEAD, prevEnd);
      const e = Math.max(s, Math.min(effEnds[i] + FADE_OUT, boundary));
      wins.push({s, e});
      prevEnd = e;
    }
    return wins;
  }, [effEnds]);

  const active: {placed: Placed[]; opacity: number}[] = [];
  for (let i = 0; i < lines.length; i++) {
    const {s, e} = dispWins[i];
    if (t < s || t > e) continue;
    const fadeInEnd = Math.min(s + FADE_IN, lines[i].winStart);  // fully visible by sing start
    const fadeOutStart = Math.max(e - FADE_OUT, effEnds[i]);     // don't dim while still voiced
    const opacity =
      interpolate(t, [s, Math.max(s + 0.001, fadeInEnd)], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      }) *
      interpolate(t, [Math.min(e - 0.001, fadeOutStart), e], [1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });
    active.push({placed: placedPerLine[i], opacity, colors: colorsFor(lines[i].style)});
  }

  fillRevealTexture(revealTex, active.flatMap((a) => a.placed), t, width, groupScale);
  sparks.material.uniforms.uTime.value = t;

  return (
    <>
      <ambientLight intensity={1} />
      <primitive object={sparks} />
      {active.map((a, i) => (
        <SustainBars
          key={'sb' + i}
          placed={a.placed}
          t={t}
          envArr={song.envelope as number[]}
          fps={fps}
          opacity={a.opacity}
        />
      ))}
      <group scale={groupScale}>
        {active.map((a, i) => (
          <LineGlyphs key={i} placed={a.placed} t={t} opacity={a.opacity} colors={a.colors} />
        ))}
      </group>
      <EffectComposer>
        <DissolveFX revealTex={revealTex} time={t} />
        <Bloom intensity={0.6 + env * 3.0} luminanceThreshold={0.3} luminanceSmoothing={0.4} mipmapBlur />
      </EffectComposer>
    </>
  );
};

export const KaraokeSong: React.FC = () => {
  const {width, height} = useVideoConfig();
  const [handle] = useState(() => delayRender('preload-font-song'));

  useEffect(() => {
    preloadFont({font: FONT, characters: song.chars ?? ''}, () => continueRender(handle));
  }, [handle]);

  return (
    <AbsoluteFill style={{backgroundColor: '#05070d'}}>
      <ThreeCanvas
        width={width}
        height={height}
        orthographic
        camera={{position: [0, 0, 600], near: 0.1, far: 3000, zoom: 1}}
        gl={{antialias: true}}
      >
        <SongScene />
      </ThreeCanvas>
      <Audio src={staticFile(song.audio ?? 'song.wav')} />
    </AbsoluteFill>
  );
};
