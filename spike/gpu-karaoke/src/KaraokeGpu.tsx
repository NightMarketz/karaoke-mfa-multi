import {forwardRef, useEffect, useMemo, useState} from 'react';
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
import {Text} from '@react-three/drei';
import {EffectComposer, Bloom} from '@react-three/postprocessing';
import {Effect} from 'postprocessing';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  DataTexture,
  Points,
  RGBAFormat,
  ShaderMaterial,
  Texture,
  Uniform,
} from 'three';
import {preloadFont} from 'troika-three-text';
import data from './spike_data.json';

// Tier-2 single-line spike. The reveal is a real per-glyph fragment-shader
// dissolve (fbm-noise threshold + lit ember frontier), an additive GPU spark
// burst fires at each syllable's attack, and bloom rides the vocal envelope.
// Shared building blocks are exported for the full-song composition (KaraokeSong).

export const FONT = staticFile('font.ttf');
export const FS = 132;                 // font size in px (ortho: 1 world unit = 1px)
// Fallback palette for the single-line spike. The full-song render overrides
// these per line from song_data.json's `palette`, which s06b fills from the
// same karaoke_styles preset the ASS path uses.
export const WAIT = '#8fa6bd';         // not-yet-sung
export const SUNG = '#ffffff';         // sung (bright -> blooms)
export const OUTLINE = '#00121f';
export type Colors = {wait: string; sung: string; outline: string};
export const DEFAULT_COLORS: Colors = {wait: WAIT, sung: SUNG, outline: OUTLINE};
export const REVEAL_LEAD = 0.35;       // s: dissolve starts this long before the sing
export const REVEAL_TAIL = 0.15;       // s: fully solid this long after the sing starts
export const SPARK_LIFE = 0.75;        // s

export type Syl = {text: string; start: number; end: number};
export type Placed = Syl & {x: number; i: number};

export const advance = (t: string) => Math.max(1, t.length) * FS * 0.52;

export function layout(syls: Syl[]): Placed[] {
  const widths = syls.map((s) => advance(s.text));
  const gap = FS * 0.34;
  const total = widths.reduce((a, b) => a + b, 0) + gap * (syls.length - 1);
  let x = -total / 2;
  return syls.map((s, i) => {
    const cx = x + widths[i] / 2;
    x += widths[i] + gap;
    return {...s, x: cx, i};
  });
}

// Fill a 1D screen-x reveal texture (256px) from laid-out syllables at time t.
// bandsScale lets callers apply the group "breathing" scale to the bands.
export function fillRevealTexture(
  tex: DataTexture,
  placed: Placed[],
  t: number,
  width: number,
  bandsScale: number,
): void {
  const bands = placed.map((s) => {
    const half = (advance(s.text) / 2) * 1.08 * bandsScale;
    const cx = s.x * bandsScale;
    const reveal = interpolate(t, [s.start - REVEAL_LEAD, s.start + REVEAL_TAIL], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return {min: 0.5 + (cx - half) / width, max: 0.5 + (cx + half) / width, reveal};
  });
  const buf = tex.image.data as Uint8Array;
  for (let x = 0; x < 256; x++) {
    const ux = x / 255;
    let r = 1;
    for (let i = 0; i < bands.length; i++) {
      if (ux >= bands[i].min && ux < bands[i].max) {
        r = bands[i].reveal;
        break;
      }
    }
    buf[x * 4] = Math.round(r * 255);
  }
  tex.needsUpdate = true;
}

export function newRevealTexture(): DataTexture {
  const buf = new Uint8Array(256 * 4).fill(255);
  const tex = new DataTexture(buf, 256, 1, RGBAFormat);
  tex.needsUpdate = true;
  return tex;
}

// ── Dissolve effect (postprocessing) ──────────────────────────────────────
// postprocessing v6 is GLSL3: sample with texture(), and custom uniforms MUST
// be declared in the shader string (the lib prefixes them e0…).
export const DISSOLVE_FRAG = /* glsl */ `
uniform sampler2D uRevealTex;
uniform float uTime;
uniform float uEdge;
float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vnoise(vec2 p){
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  float a = hash(i), b = hash(i + vec2(1.0, 0.0)), c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++){ s += a * vnoise(p); p *= 2.03; a *= 0.5; } return s; }

void mainImage(const in vec4 inputColor, const in vec2 uv, out vec4 outputColor){
  float r = texture(uRevealTex, vec2(uv.x, 0.5)).r;          // 0 dissolved .. 1 solid
  float n = clamp(fbm(uv * vec2(26.0, 15.0) + uTime * 0.15) * 1.15, 0.0, 1.0);
  float W = uEdge;
  float mask = 1.0 - smoothstep(r, r + W, n);                 // eaten where noise > reveal
  float edge = smoothstep(r, r + W * 0.5, n) * (1.0 - smoothstep(r + W * 0.5, r + W, n));
  // confine the ember to actual glyph pixels (inputColor is the pre-erosion text)
  float onText = smoothstep(0.05, 0.22, dot(inputColor.rgb, vec3(0.299, 0.587, 0.114)));
  vec3 ember = vec3(1.0, 0.55, 0.16) * edge * 2.4 * onText;   // lit dissolve frontier
  outputColor = vec4(inputColor.rgb * mask + ember, inputColor.a);
}
`;

export class DissolveImpl extends Effect {
  constructor(revealTex: Texture) {
    super('DissolveEffect', DISSOLVE_FRAG, {
      uniforms: new Map<string, Uniform>([
        ['uRevealTex', new Uniform(revealTex)],
        ['uTime', new Uniform(0)],
        ['uEdge', new Uniform(0.17)],
      ]),
    });
  }
}

export const DissolveFX = forwardRef<DissolveImpl, {revealTex: Texture; time: number}>(
  function DissolveFX({revealTex, time}, ref) {
    const effect = useMemo(() => new DissolveImpl(revealTex), [revealTex]);
    (effect.uniforms.get('uTime') as Uniform).value = time;
    return <primitive ref={ref} object={effect} dispose={null} />;
  },
);

// ── Spark burst (three.Points) — per-vertex attack/x so it scales past 8 ──
export const SPARK_V = /* glsl */ `
attribute vec2 aSeed;
attribute float aAttack;   // absolute seconds
attribute float aX;        // world x (px)
uniform float uTime;
uniform float uLife;
varying float vA;
float rnd(vec2 c){ return fract(sin(dot(c, vec2(41.3, 289.1))) * 43758.5453); }
void main(){
  float age = uTime - aAttack;
  if (age < 0.0 || age > uLife){ gl_Position = vec4(2.0, 2.0, 2.0, 1.0); gl_PointSize = 0.0; vA = 0.0; return; }
  float ang = rnd(aSeed) * 6.2831853;
  float spd = 180.0 + rnd(aSeed.yx) * 300.0;
  vec2 vel = vec2(cos(ang), sin(ang)) * spd;
  vec3 p = vec3(aX, 0.0, 0.0) + vec3(vel * age, 0.0);
  p.y -= 140.0 * age * age;                                   // gravity
  float f = 1.0 - age / uLife;
  vA = f;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = max(0.0, (2.0 + 7.0 * rnd(aSeed)) * f);
}
`;
export const SPARK_F = /* glsl */ `
varying float vA;
void main(){
  float r = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, r) * vA;
  vec3 col = mix(vec3(1.0, 0.68, 0.28), vec3(1.0, 1.0, 0.92), vA);
  gl_FragColor = vec4(col * a, a);
}
`;

const SPARKS_PER_SYL = 42;

// Build one Points cloud covering every syllable in `placed`, each spark
// carrying its own attack time (absolute s) and world-x.
export function makeSparks(placed: Placed[]): Points {
  const n = placed.length * SPARKS_PER_SYL;
  const seed = new Float32Array(n * 2);
  const attack = new Float32Array(n);
  const px = new Float32Array(n);
  const pos = new Float32Array(n * 3);
  for (let s = 0; s < placed.length; s++) {
    for (let k = 0; k < SPARKS_PER_SYL; k++) {
      const idx = s * SPARKS_PER_SYL + k;
      seed[idx * 2] = Math.sin(idx * 12.9898) * 0.5 + 0.5;      // deterministic
      seed[idx * 2 + 1] = Math.sin(idx * 78.233 + 1.3) * 0.5 + 0.5;
      attack[idx] = placed[s].start;
      px[idx] = placed[s].x;
    }
  }
  const geo = new BufferGeometry();
  geo.setAttribute('position', new BufferAttribute(pos, 3));
  geo.setAttribute('aSeed', new BufferAttribute(seed, 2));
  geo.setAttribute('aAttack', new BufferAttribute(attack, 1));
  geo.setAttribute('aX', new BufferAttribute(px, 1));
  const mat = new ShaderMaterial({
    uniforms: {uTime: {value: 0}, uLife: {value: SPARK_LIFE}},
    vertexShader: SPARK_V,
    fragmentShader: SPARK_F,
    transparent: true,
    blending: AdditiveBlending,
    depthWrite: false,
    depthTest: false,
  });
  return new Points(geo, mat);
}

// Draw laid-out glyphs for one line (SDF text, wait/sung colour by sing ramp).
export const LineGlyphs: React.FC<{
  placed: Placed[];
  t: number;
  opacity?: number;
  colors?: Colors;
}> = ({
  placed,
  t,
  opacity = 1,
  colors = DEFAULT_COLORS,
}) => (
  <>
    {placed.map((s) => {
      const sungRamp = interpolate(t, [s.start, s.end], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });
      return (
        <Text
          key={s.i}
          font={FONT}
          fontSize={FS}
          position={[s.x, 0, 0]}
          color={sungRamp > 0.001 ? colors.sung : colors.wait}
          anchorX="center"
          anchorY="middle"
          fillOpacity={opacity}
          outlineWidth={FS * 0.02}
          outlineColor={colors.outline}
          outlineOpacity={opacity}
        >
          {s.text}
        </Text>
      );
    })}
  </>
);

// ── Guitar-Hero sustain bar — makes melismas / held notes legible ─────────
// A held note draws a track under the glyph whose LENGTH ∝ its duration; a
// bright fill "consumes" it over [start,end] (remaining = sustain left), and a
// strike head rides the fill, glowing with the live vocal envelope. Only notes
// longer than SUSTAIN_MIN get a bar, so short syllables stay clean.
// ponytail: "extended note" = the VOICED span of a syllable (RMS envelope >
// SUSTAIN_ENV_THR inside [start,end]) lasting >= SUSTAIN_MIN. Trimming to the
// voiced span kills phantom bars over silence (false_long_tail) and starts the
// bar at the real vocal attack. Still symbolic-ish: no pitch, fixed threshold —
// see README "Extended-note (sustain) identification" for the deeper fix path.
export const SUSTAIN_MIN = 0.45;    // s — trimmed voiced span shorter than this → no bar
export const SUSTAIN_ENV_THR = 0.15; // normalized RMS above this counts as "voiced"
const BAR_Y = -FS * 0.86;           // px below the glyph baseline
const BAR_H = FS * 0.13;            // bar thickness (px)
const PX_PER_S = 240;               // hold length scale (px per second held)
const BAR_MAX = 1600;               // px cap — centered, so ±800 stays inside 1920
const MAX_TAIL = 8;                 // s — cap on tail extension past a clipped syllable

// Voiced span of a syllable from the RMS envelope. Anchors at the first voiced
// frame inside the aligned window [start,end], then extends the tail PAST `end`
// through a held note up to `maxEnd`, stopping at a real silence gap. This recovers
// melismas the aligner clipped to ~0 (the "snap" @70.7s is aligned 0.18s but held
// ~5s; the pipeline calls that possible_lost_tail). Null if the syllable window
// itself has no voiced audio.
export function voicedSpan(
  start: number,
  end: number,
  maxEnd: number,
  env: number[],
  fps: number,
  thr: number,
): [number, number] | null {
  const f0 = Math.max(0, Math.floor(start * fps));
  const fEnd = Math.min(env.length - 1, Math.ceil(end * fps));
  const fMax = Math.min(env.length - 1, Math.ceil(maxEnd * fps));
  const gapMax = Math.max(1, Math.round(0.25 * fps));       // tolerate dips up to 0.25s
  let a = -1;
  for (let f = f0; f <= fEnd; f++) {
    if (env[f] > thr) { a = f; break; }                     // syllable must be voiced
  }
  if (a < 0) return null;
  let b = a;
  let gap = 0;
  for (let f = a; f <= fMax; f++) {
    if (env[f] > thr) { b = f; gap = 0; }
    else if (++gap > gapMax) break;                         // real silence → tail ends
  }
  return [a / fps, (b + 1) / fps];
}

// Latest voiced-tail end across a line's syllables (>= its symbolic winEnd once
// max'd by the caller). Lets the full-song comp keep a line — text AND bar — on
// screen while a clipped-alignment melisma is still being held.
export function lineTailEnd(placed: Placed[], envArr: number[], fps: number, thr: number): number {
  let end = 0;
  placed.forEach((s, i) => {
    const maxEnd = i + 1 < placed.length ? placed[i + 1].start - 0.03 : s.start + MAX_TAIL;
    const sp = voicedSpan(s.start, s.end, maxEnd, envArr, fps, thr);
    if (sp) end = Math.max(end, sp[1]);
  });
  return end;
}

export const SustainBars: React.FC<{
  placed: Placed[];
  t: number;
  envArr: number[];
  fps: number;
  opacity?: number;
}> = ({placed, t, envArr, fps, opacity = 1}) => {
  // trim each syllable to its voiced span once (placed refs are stable)
  const spans = useMemo(
    () =>
      placed.map((s, i) => {
        // let the tail run to the next syllable (or a cap for a line's last note)
        const maxEnd = i + 1 < placed.length ? placed[i + 1].start - 0.03 : s.start + MAX_TAIL;
        return voicedSpan(s.start, s.end, maxEnd, envArr, fps, SUSTAIN_ENV_THR);
      }),
    [placed, envArr, fps],
  );
  const headEnv = envArr[Math.min(envArr.length - 1, Math.round(t * fps))] ?? 0;
  const headGlow = Math.min(1, 0.45 + headEnv * 1.6);              // head rides the voice

  // qualifying holds right now (trimmed voiced span, long enough, in window)
  const bars = placed
    .map((s, idx) => ({s, span: spans[idx]}))
    .filter(({span}) => span && span[1] - span[0] >= SUSTAIN_MIN && t >= span[0] - 0.05 && t <= span[1] + 0.15);

  return (
    <>
      {bars.map(({s, span}, k) => {
        const [vs, ve] = span as [number, number];
        // CENTERED anchor (not glyph-x): a long melisma's bar must stay fully on
        // screen, so it can't hang off a right-side word. Length ∝ duration, capped.
        const L = Math.min(BAR_MAX, (ve - vs) * PX_PER_S);
        const left = -L / 2;
        const progress = Math.min(1, Math.max(0, (t - vs) / (ve - vs)));
        const held = t >= vs && t <= ve;
        const fillL = Math.max(1, L * progress);
        const y = BAR_Y - k * BAR_H * 2.2;                         // stack if >1 hold at once
        return (
          <group key={s.i} position={[0, y, 0]}>
            <mesh position={[left + L / 2, 0, 0]}>
              <planeGeometry args={[L, BAR_H]} />
              <meshBasicMaterial color="#0a3a4a" transparent opacity={0.5 * opacity} />
            </mesh>
            <mesh position={[left + fillL / 2, 0, 0.1]}>
              <planeGeometry args={[fillL, BAR_H]} />
              <meshBasicMaterial color={held ? '#66f0ff' : '#2f8ea6'} transparent opacity={opacity} />
            </mesh>
            {held && (
              <mesh position={[left + fillL, 0, 0.2]}>
                <planeGeometry args={[BAR_H * (1.4 + headEnv), BAR_H * 2.6]} />
                <meshBasicMaterial color="#ffffff" transparent opacity={headGlow * opacity} />
              </mesh>
            )}
          </group>
        );
      })}
    </>
  );
};

const Scene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const t = frame / fps;
  const env = (data.envelope as number[])[Math.min(frame, data.envelope.length - 1)] ?? 0;

  const placed = useMemo(() => layout(data.syllables as Syl[]), []);
  const groupScale = 1 + env * 0.04;

  const revealTex = useMemo(() => newRevealTexture(), []);
  const sparks = useMemo(() => makeSparks(placed), [placed]);

  fillRevealTexture(revealTex, placed, t, width, groupScale);
  sparks.material.uniforms.uTime.value = t;

  return (
    <>
      <ambientLight intensity={1} />
      <primitive object={sparks} />
      <SustainBars placed={placed} t={t} envArr={data.envelope as number[]} fps={fps} />
      <group scale={groupScale}>
        <LineGlyphs placed={placed} t={t} />
      </group>
      <EffectComposer>
        <DissolveFX revealTex={revealTex} time={t} />
        <Bloom intensity={0.6 + env * 3.0} luminanceThreshold={0.3} luminanceSmoothing={0.4} mipmapBlur />
      </EffectComposer>
    </>
  );
};

export const KaraokeGpu: React.FC = () => {
  const {width, height} = useVideoConfig();
  const [handle] = useState(() => delayRender('preload-font'));

  useEffect(() => {
    preloadFont(
      {font: FONT, characters: data.text + ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'},
      () => continueRender(handle),
    );
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
        <Scene />
      </ThreeCanvas>
      <Audio src={staticFile('segment.wav')} />
    </AbsoluteFill>
  );
};
