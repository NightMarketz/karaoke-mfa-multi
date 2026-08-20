# Motor de Jogo de Karaoke com Tracking de Voz — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar um job já processado do pipeline em uma partida jogável no navegador, onde a voz do jogador é comparada em tempo real com a melodia da música e pontuada.

**Architecture:** O ROSVOT produz `melody.json` por job (contrato estável); o navegador lê esse arquivo, captura o microfone, detecta pitch quadro a quadro e pontua em duas pistas (afinação e ritmo). Toda a lógica de pontuação e de detecção de pitch vive em funções puras testáveis fora do navegador; o arquivo de glue (`game.js`) não contém regra de negócio.

**Tech Stack:** Python 3.10+ / Flask (servidor e estágio de pipeline), JavaScript ESM sem bundler (frontend), `node --test` (testes JS), `unittest` + pytest runner (testes Python).

**Spec:** [docs/superpowers/specs/2026-08-20-karaoke-voice-game-design.md](../specs/2026-08-20-karaoke-voice-game-design.md)

## Global Constraints

- **Linhagem:** checkout principal, branch `mvp-pipeline-runner`. NÃO usar a linhagem `master` (o `03b_rosvot_inference.py` de lá é placeholder).
- **Sem dependência JS nova e sem bundler.** O Flask serve `static/` puro.
- **Sem dependência Python nova** além do que o ROSVOT exigir no próprio env dele.
- **Todo teste tem controle negativo.** Cerca que nunca foi vista vermelha não é cerca: onde o plano manda sabotar e verificar vermelho, esse passo não é opcional.
- **Cardinalidade antes do veredito.** Nenhuma asserção sobre uma coleção sem antes afirmar que ela não está vazia.
- **Número sempre com denominador.** Relatório de medição diz "168 de 474", nunca "168".
- **Tolerância de afinação:** ±1 semitom. **Clarity mínima:** 0.5. **Lead-in descartado:** 40 ms. **Corte da pista de ritmo:** nota < 100 ms ou linha `style == "rap"`. **Janela de ritmo:** ±120 ms. **Ponto de ritmo:** 50. **Ponto de afinação máximo:** 100. **Multiplicador de combo:** `min(1 + combo/10, 2)`.
- **Faixa de pitch:** 65 Hz a 1000 Hz.
- **Commits:** um por task, mensagem em português, prefixo `feat:` / `test:` / `docs:`.

## Desvio consciente da spec (decidido no planejamento)

A spec §5.1/§5.2 previa um `AudioWorklet` para a detecção de pitch. Trocado por
**`AnalyserNode.getFloatTimeDomainData()` chamado dentro do mesmo `requestAnimationFrame`
que já desenha a tela**. Motivos:

1. Elimina um arquivo, o `MessagePort` e o risco de ESM dentro de worklet.
2. A amostra de pitch passa a ter exatamente o mesmo instante que o quadro desenhado e o
   mesmo `instrumental.currentTime` — some uma fonte de erro de sincronia.
3. Custo: com decimação para 16 kHz a análise custa ~126 mil iterações por quadro, ~0,15 ms.
   Cabe folgado nos 16,7 ms de um quadro a 60 fps.

Consequência: a tela de erro "navegador sem AudioWorklet" vira **"navegador sem
`getUserMedia`"**. A spec foi atualizada junto com este plano.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
| --- | --- | --- |
| `docs/superpowers/plans/assets/rosvot-schema.md` | schema real de saída do ROSVOT, registrado na prática | 0 |
| `static/package.json` | `{"type":"module"}` — faz o Node tratar `static/*.js` como ESM. Invisível para o navegador | 1 |
| `static/game-scoring.js` | funções **puras** de pontuação. Zero DOM, zero áudio | 1 |
| `tests/game-scoring.test.mjs` | testes de pontuação (`node --test`) | 1 |
| `static/game-pitch.js` | `detectPitch()` puro (NSDF/McLeod) + `decimate()` | 2 |
| `tests/game-pitch.test.mjs` | testes do detector (`node --test`) | 2 |
| `scripts/melody_anchor.py` | ancoragem de notas em sílabas. Puro, sem I/O, sem ROSVOT | 3 |
| `tests/test_melody_anchor.py` | testes da ancoragem | 3 |
| `scripts/s05b_melody.py` | estágio CLI: roda ROSVOT, parseia, ancora, escreve `melody.json` | 4 |
| `tests/test_melody_stage.py` | testes do parser e do estágio | 4 |
| `scripts/pipeline_runner.py` | registra o estágio `melody` no plano | 5 |
| `server.py` | rotas `/job/<id>/melody.json` e `/job/<id>/game` | 6 |
| `tests/test_game_server.py` | testes das duas rotas | 6 |
| `templates/game.html` | markup das três telas | 7 |
| `static/game.js` | glue: relógio, playback, captura, render em canvas | 7 |
| `static/game-assist.js` | calibração de latência, vazamento de mic, transposição — **puras** | 8 |
| `tests/game-assist.test.mjs` | testes dos três auxiliares | 8 |

---

### Task 0: Spike — provar que o ROSVOT existe e registrar o schema real

Esta task **não é TDD**: é investigação com entregável documentado. Nenhuma outra task
pode começar antes dela, porque o parser da Task 4 depende do schema real.

**Files:**
- Create: `docs/superpowers/plans/assets/rosvot-schema.md`
- Create: `tests/fixtures/rosvot_publi_raw.json` (recorte da saída real, ~20 notas)

**Interfaces:**
- Consumes: nada.
- Produces: o arquivo `rosvot-schema.md` documentando (a) o comando exato de inferência,
  (b) o formato JSON exato de saída com um exemplo real, (c) os três números da prova de
  campo. A Task 4 lê esse documento para escrever `_rosvot_to_notes`.

- [ ] **Step 1: Subir o ROSVOT num env isolado**

ROSVOT é "Robust Singing Voice Transcription" (Li et al., 2024). Clonar o repositório
oficial e seguir o README dele para pesos e dependências. Criar env separado — **não**
instalar no env do pipeline, para não colidir com `torch`/`onnxruntime` já pinados em
`requirements.txt`.

```bash
mkdir -p vendor && cd vendor
git clone https://github.com/RickyL-2000/ROSVOT.git
cd ROSVOT && cat README.md
```

Se o repositório tiver mudado de endereço, procurar pelo nome do paper antes de desistir.

- [ ] **Step 2: Rodar a inferência no vocal da Publi**

```bash
python -c "import soundfile as sf; d,r = sf.read(r'jobs/publi-bet/vocals.wav'); print(d.shape, r)"
```

Rodar a inferência do ROSVOT sobre `jobs/publi-bet/vocals.wav` conforme o README dele,
salvando a saída bruta em `jobs/publi-bet/rosvot_raw.json`.

- [ ] **Step 3: PORTÃO — se não rodar, parar e escalar**

Se em esforço razoável o ROSVOT não produzir saída (pesos indisponíveis, CUDA
incompatível, repositório morto), **pare o plano aqui e reporte ao usuário**. Não invente
um substituto silencioso. O plano B já está especificado na spec §2: usar o F0 do CREPE
que já roda em `scripts/s03b_lyrics_align.py:1529` e hoje é descartado, mantendo o mesmo
contrato `melody.json` e trocando apenas `"source"`. Essa troca é decisão do usuário, não
do implementador.

- [ ] **Step 4: Medir a prova de campo, com denominador**

```bash
python -c "
import json
raw = json.load(open('jobs/publi-bet/rosvot_raw.json', encoding='utf-8'))
an  = json.load(open('jobs/publi-bet/analysis.json', encoding='utf-8'))
notes = raw if isinstance(raw, list) else (raw.get('notes') or raw.get('words') or [])
assert len(notes) > 0, 'ZERO notas: veredito sobre conjunto vazio nao vale'
lines = [(l['start'], l['end']) for l in an['lines']]
span_linhas = sum(b - a for a, b in lines)
def dentro(n):
    return any(min(n['end'], b) - max(n['start'], a) > 0 for a, b in lines)
orfas = sum(1 for n in notes if not dentro(n))
cob = 0.0
for a, b in lines:
    for n in notes:
        ov = min(n['end'], b) - max(n['start'], a)
        if ov > 0: cob += ov
print('notas:      %d' % len(notes))
print('orfas:      %d de %d' % (orfas, len(notes)))
print('cobertura:  %.1f s de %.1f s de span de linha' % (cob, span_linhas))
"
```

O denominador do span de linha na Publi é **145,3 s**. Anotar os três números.

- [ ] **Step 5: Escrever o documento de schema**

Criar `docs/superpowers/plans/assets/rosvot-schema.md` com: comando exato de inferência,
o JSON de uma nota real copiado da saída (não parafraseado), o nome exato de cada campo
(`start`? `onset`? `note`? `pitch`? `midi`?), a unidade do tempo (segundos ou frames), a
unidade do pitch (MIDI ou Hz), e os três números do Step 4 com seus denominadores.

- [ ] **Step 6: Recortar a fixture**

```bash
python -c "
import json, pathlib
raw = json.load(open('jobs/publi-bet/rosvot_raw.json', encoding='utf-8'))
notes = raw if isinstance(raw, list) else (raw.get('notes') or raw.get('words') or [])
assert len(notes) >= 20, 'fixture precisa de pelo menos 20 notas, veio %d' % len(notes)
pathlib.Path('tests/fixtures').mkdir(parents=True, exist_ok=True)
json.dump(notes[:20], open('tests/fixtures/rosvot_publi_raw.json','w',encoding='utf-8'), indent=2)
print('fixture: 20 de %d notas' % len(notes))
"
```

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/plans/assets/rosvot-schema.md tests/fixtures/rosvot_publi_raw.json
git commit -m "docs: registra schema real do ROSVOT e fixture da Publi"
```

---

### Task 1: Pontuação pura (`static/game-scoring.js`)

Nenhuma dependência do ROSVOT. Pode ser feita em paralelo com a Task 0.

**Files:**
- Create: `static/package.json`
- Create: `static/game-scoring.js`
- Test: `tests/game-scoring.test.mjs`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `hzToMidi(hz: number) -> number`
  - `foldSemitone(diff: number) -> number` (resultado em `[-6, 6)`)
  - `scorePitchNote(frames: {t,hz,clarity}[], targetMidi: number, note: {start,end}) -> number` (0..100)
  - `scoreRhythmNote(frames: {t,hz,clarity}[], note: {start}) -> number` (0 ou 50)
  - `comboMultiplier(combo: number) -> number`
  - `finalScore(results: {score,max}[]) -> {percent: number, maxCombo: number}`
  - `grade(percent: number) -> "S"|"A"|"B"|"C"|"D"`

- [ ] **Step 1: Criar o `static/package.json`**

O Node decide se um `.js` é ESM pelo `package.json` mais próximo. Sem este arquivo,
`import` de `static/game-scoring.js` num teste falha com `Cannot use import statement
outside a module`. O navegador ignora este arquivo completamente.

```json
{
  "type": "module"
}
```

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/game-scoring.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  hzToMidi, foldSemitone, scorePitchNote, scoreRhythmNote,
  comboMultiplier, finalScore, grade,
} from '../static/game-scoring.js';

const frames = (specs) => specs.map(([t, hz]) => ({ t, hz, clarity: 0.9 }));

test('hzToMidi: 440 Hz e A4 = 69', () => {
  assert.equal(Math.round(hzToMidi(440)), 69);
  assert.equal(Math.round(hzToMidi(220)), 57);
});

test('foldSemitone: oitava nao conta', () => {
  assert.equal(foldSemitone(11), -1);
  assert.equal(foldSemitone(-1), -1);
  assert.equal(foldSemitone(12), 0);
  assert.equal(foldSemitone(0), 0);
});

test('afinacao: dentro de 1 semitom da 100', () => {
  const f = frames([[1.10, 440], [1.15, 440], [1.20, 440]]);
  assert.equal(scorePitchNote(f, 69, { start: 1.0, end: 1.3 }), 100);
});

test('CONTROLE NEGATIVO afinacao: 3 semitons fora da 0', () => {
  const f = frames([[1.10, 523.25], [1.15, 523.25], [1.20, 523.25]]);
  assert.equal(scorePitchNote(f, 69, { start: 1.0, end: 1.3 }), 0);
});

test('CONTROLE NEGATIVO afinacao: lista vazia e MISS, nunca 100', () => {
  assert.equal(scorePitchNote([], 69, { start: 1.0, end: 1.3 }), 0);
});

test('CONTROLE NEGATIVO afinacao: frames fora da janela nao contam', () => {
  const f = frames([[0.5, 440], [5.0, 440]]);
  assert.equal(scorePitchNote(f, 69, { start: 1.0, end: 1.3 }), 0);
});

test('afinacao: os primeiros 40ms sao descartados', () => {
  const f = frames([[1.01, 523.25], [1.10, 440], [1.20, 440]]);
  assert.equal(scorePitchNote(f, 69, { start: 1.0, end: 1.3 }), 100);
});

test('ritmo: ataque 80ms antes do inicio vale 50', () => {
  const f = frames([[1.92, 200]]);
  assert.equal(scoreRhythmNote(f, { start: 2.0 }), 50);
});

test('CONTROLE NEGATIVO ritmo: ataque 300ms depois vale 0', () => {
  const f = frames([[2.30, 200]]);
  assert.equal(scoreRhythmNote(f, { start: 2.0 }), 0);
});

test('CONTROLE NEGATIVO ritmo: sem frames vale 0', () => {
  assert.equal(scoreRhythmNote([], { start: 2.0 }), 0);
});

test('combo: multiplicador cresce e satura em 2', () => {
  assert.equal(comboMultiplier(0), 1);
  assert.equal(comboMultiplier(5), 1.5);
  assert.equal(comboMultiplier(50), 2);
});

test('final: partida perfeita da 100 por cento', () => {
  const rs = [{ score: 100, max: 100 }, { score: 100, max: 100 }, { score: 50, max: 50 }];
  const out = finalScore(rs);
  assert.equal(out.percent, 1);
  assert.equal(out.maxCombo, 3);
});

test('TETO DO RAP: linha de ritmo perfeita nao supera afinacao perfeita', () => {
  const rap   = finalScore([{ score: 50,  max: 50  }, { score: 50,  max: 50  }]);
  const canto = finalScore([{ score: 100, max: 100 }, { score: 100, max: 100 }]);
  assert.equal(rap.percent, canto.percent);
  const rapBruto   = 50 * 2;
  const cantoBruto = 100 * 2;
  assert.ok(rapBruto < cantoBruto, 'rap nao pode render mais ponto bruto que canto');
});

test('CARDINALIDADE: lista de resultados vazia nao vale veredito', () => {
  assert.throws(() => finalScore([]), /vazia/);
});

test('grade: fronteiras', () => {
  assert.equal(grade(0.96), 'S');
  assert.equal(grade(0.95), 'S');
  assert.equal(grade(0.94), 'A');
  assert.equal(grade(0.10), 'D');
});
```

- [ ] **Step 3: Rodar o teste e verificar que falha**

```bash
node --test tests/game-scoring.test.mjs
```

Esperado: FAIL com `Cannot find module '../static/game-scoring.js'`.

- [ ] **Step 4: Implementar o mínimo**

Criar `static/game-scoring.js`:

```javascript
// Pontuacao pura do jogo de karaoke. Zero DOM, zero audio, zero estado global —
// tudo aqui e testavel com `node --test tests/game-scoring.test.mjs`.

export const CLARITY_MIN = 0.5;
export const LEAD_IN_S   = 0.04;   // ataque da silaba e ruido para o detector
export const TOLERANCE   = 1;      // semitons
export const RHYTHM_WINDOW_S = 0.12;
export const RHYTHM_POINTS   = 50; // metade de uma nota de afinacao perfeita

export function hzToMidi(hz) {
  return 69 + 12 * Math.log2(hz / 440);
}

// Distancia em semitons ignorando oitava. Resultado em [-6, 6).
export function foldSemitone(diff) {
  return (((diff + 6) % 12) + 12) % 12 - 6;
}

export function scorePitchNote(frames, targetMidi, note) {
  const from = note.start + LEAD_IN_S;
  const win = frames.filter(
    (f) => f.t >= from && f.t <= note.end && f.clarity > CLARITY_MIN && f.hz > 0,
  );
  if (win.length === 0) return 0;   // conjunto vazio e MISS, nunca acerto
  const hits = win.filter(
    (f) => Math.abs(foldSemitone(hzToMidi(f.hz) - targetMidi)) <= TOLERANCE,
  ).length;
  const frac = hits / win.length;
  return frac < 0.25 ? 0 : Math.round(100 * frac);
}

export function scoreRhythmNote(frames, note) {
  const hit = frames.some(
    (f) => f.clarity > CLARITY_MIN && Math.abs(f.t - note.start) <= RHYTHM_WINDOW_S,
  );
  return hit ? RHYTHM_POINTS : 0;
}

export function comboMultiplier(combo) {
  return Math.min(1 + combo / 10, 2);
}

export function finalScore(results) {
  if (!Array.isArray(results) || results.length === 0) {
    throw new Error('finalScore: lista de resultados vazia — sem cardinalidade nao ha veredito');
  }
  let combo = 0, maxCombo = 0, obtido = 0, ideal = 0, comboIdeal = 0;
  for (const r of results) {
    obtido += r.score * comboMultiplier(combo);
    ideal  += r.max   * comboMultiplier(comboIdeal);
    comboIdeal += 1;                       // a partida perfeita nunca quebra o combo
    combo = r.score >= 50 ? combo + 1 : 0;
    if (combo > maxCombo) maxCombo = combo;
  }
  return { percent: ideal === 0 ? 0 : obtido / ideal, maxCombo };
}

export function grade(percent) {
  if (percent >= 0.95) return 'S';
  if (percent >= 0.85) return 'A';
  if (percent >= 0.70) return 'B';
  if (percent >= 0.50) return 'C';
  return 'D';
}
```

- [ ] **Step 5: Rodar o teste e verificar que passa**

```bash
node --test tests/game-scoring.test.mjs
```

Esperado: PASS, 14 testes.

- [ ] **Step 6: Verificar o controle negativo de verdade**

Sabotar deliberadamente e confirmar vermelho. Em `static/game-scoring.js`, trocar
`if (win.length === 0) return 0;` por `if (win.length === 0) return 100;` e rodar:

```bash
node --test tests/game-scoring.test.mjs
```

Esperado: **FAIL** em "lista vazia e MISS". Se passar verde, o teste não está medindo
nada e precisa ser consertado. Desfazer a sabotagem e rodar de novo até verde.

- [ ] **Step 7: Commit**

```bash
git add static/package.json static/game-scoring.js tests/game-scoring.test.mjs
git commit -m "feat: pontuacao pura do jogo de karaoke em duas pistas"
```

---

### Task 2: Detector de pitch (`static/game-pitch.js`)

**Files:**
- Create: `static/game-pitch.js`
- Test: `tests/game-pitch.test.mjs`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `decimate(buf: Float32Array, factor: number) -> Float32Array`
  - `detectPitch(buf: Float32Array, sampleRate: number) -> {hz: number, clarity: number} | null`

`detectPitch` devolve `null` para silêncio ou sinal sem periodicidade. **Nunca** devolve
uma nota inventada — é isso que impede o jogo de pontuar ruído de ventilador.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/game-pitch.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { detectPitch, decimate } from '../static/game-pitch.js';
import { hzToMidi } from '../static/game-scoring.js';

function sine(hz, sampleRate, n, amp = 0.5) {
  const b = new Float32Array(n);
  for (let i = 0; i < n; i++) b[i] = amp * Math.sin((2 * Math.PI * hz * i) / sampleRate);
  return b;
}

const SR = 16000;
const N  = 683;   // ~43 ms, o que sobra de 2048 amostras a 48 kHz apos decimar por 3

test('CARDINALIDADE: o buffer de teste nao esta vazio', () => {
  assert.ok(sine(220, SR, N).length > 0);
});

test('detecta 220 Hz dentro de 0.3 semitom', () => {
  const r = detectPitch(sine(220, SR, N), SR);
  assert.ok(r !== null, 'devolveu null para uma senoide limpa');
  assert.ok(
    Math.abs(hzToMidi(r.hz) - hzToMidi(220)) < 0.3,
    `esperado ~220 Hz, veio ${r.hz.toFixed(1)} Hz`,
  );
});

test('detecta 440 Hz dentro de 0.3 semitom', () => {
  const r = detectPitch(sine(440, SR, N), SR);
  assert.ok(r !== null);
  assert.ok(Math.abs(hzToMidi(r.hz) - hzToMidi(440)) < 0.3);
});

test('detecta 82 Hz (E2, extremo grave) dentro de 0.5 semitom', () => {
  const r = detectPitch(sine(82.41, SR, N), SR);
  assert.ok(r !== null, 'perdeu o extremo grave da faixa');
  assert.ok(Math.abs(hzToMidi(r.hz) - hzToMidi(82.41)) < 0.5);
});

test('CONTROLE NEGATIVO: silencio devolve null, nunca uma nota', () => {
  assert.equal(detectPitch(new Float32Array(N), SR), null);
});

test('CONTROLE NEGATIVO: ruido branco devolve null', () => {
  const b = new Float32Array(N);
  // PRNG deterministico com Math.imul: multiplicacao de 32 bits sem estourar
  // a mantissa de 53 bits — com aritmetica de ponto flutuante o "ruido" vira
  // periodico e o teste passaria por acidente.
  let seed = 42;
  for (let i = 0; i < N; i++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) | 0;
    b[i] = (seed >>> 0) / 0xffffffff * 2 - 1;
  }
  assert.equal(detectPitch(b, SR), null, 'inventou nota a partir de ruido');
});

test('decimate reduz o tamanho pelo fator', () => {
  const out = decimate(sine(220, 48000, 2048), 3);
  assert.equal(out.length, Math.floor(2048 / 3));
});

test('decimate preserva a frequencia', () => {
  const r = detectPitch(decimate(sine(220, 48000, 2048), 3), 16000);
  assert.ok(r !== null);
  assert.ok(Math.abs(hzToMidi(r.hz) - hzToMidi(220)) < 0.3);
});
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

```bash
node --test tests/game-pitch.test.mjs
```

Esperado: FAIL com `Cannot find module '../static/game-pitch.js'`.

- [ ] **Step 3: Implementar o mínimo**

Criar `static/game-pitch.js`:

```javascript
// Detector de pitch NSDF (McLeod Pitch Method). Puro: entra Float32Array, sai
// {hz, clarity} ou null. Roda no mesmo requestAnimationFrame que desenha a tela.

export const FMIN = 65;    // Hz — abaixo disso e ruido de sala, nao canto
export const FMAX = 1000;
export const CLARITY_FLOOR = 0.5;
export const RMS_FLOOR = 1e-3;

// Media de `factor` amostras vizinhas antes de subamostrar: filtro anti-aliasing
// pobre, suficiente porque so nos interessa a banda ate ~2 kHz.
export function decimate(buf, factor) {
  const n = Math.floor(buf.length / factor);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < factor; k++) acc += buf[i * factor + k];
    out[i] = acc / factor;
  }
  return out;
}

export function detectPitch(buf, sampleRate) {
  const n = buf.length;
  if (n === 0) return null;

  let energia = 0;
  for (let i = 0; i < n; i++) energia += buf[i] * buf[i];
  if (Math.sqrt(energia / n) < RMS_FLOOR) return null;   // silencio

  const tauMin = Math.max(2, Math.floor(sampleRate / FMAX));
  const tauMax = Math.min(Math.floor(sampleRate / FMIN), n - 2);
  if (tauMax <= tauMin) return null;

  const nsdf = new Float32Array(tauMax + 2);
  let maior = 0;
  for (let tau = tauMin; tau <= tauMax; tau++) {
    let acf = 0, div = 0;
    for (let i = 0; i + tau < n; i++) {
      acf += buf[i] * buf[i + tau];
      div += buf[i] * buf[i] + buf[i + tau] * buf[i + tau];
    }
    const v = div > 0 ? (2 * acf) / div : 0;
    nsdf[tau] = v;
    if (v > maior) maior = v;
  }
  if (maior < CLARITY_FLOOR) return null;   // sem periodicidade: ruido

  // McLeod: o primeiro pico acima de 90% do maior, nao o maior — e isso que evita
  // travar na oitava abaixo.
  const corte = 0.9 * maior;
  let pico = -1;
  for (let tau = tauMin + 1; tau < tauMax; tau++) {
    if (nsdf[tau] > nsdf[tau - 1] && nsdf[tau] >= nsdf[tau + 1] && nsdf[tau] >= corte) {
      pico = tau;
      break;
    }
  }
  if (pico < 0) return null;

  const a = nsdf[pico - 1], b = nsdf[pico], c = nsdf[pico + 1];
  const denom = a - 2 * b + c;
  const shift = denom !== 0 ? (a - c) / (2 * denom) : 0;
  const tau = pico + shift;
  if (tau <= 0) return null;

  return { hz: sampleRate / tau, clarity: b };
}
```

- [ ] **Step 4: Rodar o teste e verificar que passa**

```bash
node --test tests/game-pitch.test.mjs
```

Esperado: PASS, 8 testes. Se o teste de 82 Hz falhar, o buffer é curto demais para o
período grave — aumentar `N` no teste para 1024 e a janela do `game.js` (Task 7) para
4096 amostras a 48 kHz, e anotar a mudança.

- [ ] **Step 5: Verificar o controle negativo de verdade**

Trocar `if (maior < CLARITY_FLOOR) return null;` por `if (false) return null;` e rodar:

```bash
node --test tests/game-pitch.test.mjs
```

Esperado: **FAIL** em "ruido branco devolve null". Desfazer e confirmar verde.

- [ ] **Step 6: Commit**

```bash
git add static/game-pitch.js tests/game-pitch.test.mjs
git commit -m "feat: detector de pitch NSDF puro para o jogo"
```

---

### Task 3: Ancoragem de notas em sílabas (`scripts/melody_anchor.py`)

Puro, sem I/O e sem ROSVOT — pode rodar antes da Task 0 terminar.

**Files:**
- Create: `scripts/melody_anchor.py`
- Test: `tests/test_melody_anchor.py`

**Interfaces:**
- Consumes: nada.
- Produces: `anchor_notes(raw_notes: list[dict], analysis: dict) -> tuple[list[dict], int]`
  - `raw_notes`: itens com as chaves `start`, `end`, `midi` (floats em segundos, int MIDI).
  - retorno: `(notes, orphans)` onde cada nota tem exatamente as chaves
    `start, end, midi, syllable_id, line_id, text, style`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_melody_anchor.py`:

```python
import unittest

from scripts.melody_anchor import anchor_notes


def _analysis():
    """Duas linhas, uma silaba por palavra. Espelha a forma real do analysis.json."""
    return {
        "lines": [
            {
                "text": "la", "start": 1.0, "end": 2.0, "style": "chorus",
                "words": [{
                    "word": "la", "start": 1.0, "end": 2.0, "id": "L001_W001",
                    "syllables": [{
                        "syllable_id": "L001_W001_S001", "line_id": "L001",
                        "word_id": "L001_W001", "text": "la",
                        "start": 1.0, "end": 1.5,
                    }],
                }],
            },
            {
                "text": "vai", "start": 3.0, "end": 4.0, "style": "rap",
                "words": [{
                    "word": "vai", "start": 3.0, "end": 4.0, "id": "L002_W001",
                    "syllables": [{
                        "syllable_id": "L002_W001_S001", "line_id": "L002",
                        "word_id": "L002_W001", "text": "vai",
                        "start": 3.0, "end": 3.4,
                    }],
                }],
            },
        ]
    }


class AnchorNotesTests(unittest.TestCase):
    def test_nota_sobreposta_ancora_na_silaba(self):
        notes, orphans = anchor_notes(
            [{"start": 1.05, "end": 1.45, "midi": 62}], _analysis()
        )
        self.assertEqual(len(notes), 1)          # cardinalidade antes do veredito
        self.assertEqual(orphans, 0)
        self.assertEqual(notes[0]["syllable_id"], "L001_W001_S001")
        self.assertEqual(notes[0]["line_id"], "L001")
        self.assertEqual(notes[0]["text"], "la")
        self.assertEqual(notes[0]["style"], "chorus")
        self.assertEqual(notes[0]["midi"], 62)

    def test_style_rap_e_copiado_da_linha(self):
        notes, _ = anchor_notes([{"start": 3.1, "end": 3.3, "midi": 60}], _analysis())
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["style"], "rap")

    def test_CONTROLE_NEGATIVO_nota_fora_de_silaba_vira_orfa(self):
        notes, orphans = anchor_notes(
            [{"start": 9.0, "end": 9.5, "midi": 60}], _analysis()
        )
        self.assertEqual(notes, [])
        self.assertEqual(orphans, 1)

    def test_nota_sobre_duas_silabas_escolhe_a_de_maior_sobreposicao(self):
        analysis = _analysis()
        analysis["lines"][0]["words"][0]["syllables"].append({
            "syllable_id": "L001_W001_S002", "line_id": "L001",
            "word_id": "L001_W001", "text": "ra", "start": 1.5, "end": 2.0,
        })
        # 1.4 -> 1.9: 0.1 s na primeira silaba, 0.4 s na segunda
        notes, _ = anchor_notes([{"start": 1.4, "end": 1.9, "midi": 62}], analysis)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["syllable_id"], "L001_W001_S002")

    def test_CONTROLE_NEGATIVO_encosto_sem_sobreposicao_nao_ancora(self):
        # termina exatamente onde a silaba comeca: sobreposicao zero nao e sobreposicao
        notes, orphans = anchor_notes(
            [{"start": 0.5, "end": 1.0, "midi": 62}], _analysis()
        )
        self.assertEqual(notes, [])
        self.assertEqual(orphans, 1)

    def test_lista_vazia_devolve_vazio_sem_estourar(self):
        notes, orphans = anchor_notes([], _analysis())
        self.assertEqual(notes, [])
        self.assertEqual(orphans, 0)

    def test_saida_tem_exatamente_as_chaves_do_contrato(self):
        notes, _ = anchor_notes([{"start": 1.05, "end": 1.45, "midi": 62}], _analysis())
        self.assertEqual(len(notes), 1)
        self.assertEqual(
            set(notes[0]),
            {"start", "end", "midi", "syllable_id", "line_id", "text", "style"},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

```bash
python -m pytest tests/test_melody_anchor.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'scripts.melody_anchor'`.

- [ ] **Step 3: Implementar o mínimo**

Criar `scripts/melody_anchor.py`:

```python
"""Ancoragem de notas cantadas nas silabas do analysis.json.

Puro: nao le arquivo, nao chama modelo, nao depende do produtor das notas.
Trocar ROSVOT por outro produtor nao toca neste arquivo.
"""

from __future__ import annotations

from typing import Any

# Chaves exatas do contrato melody.json (spec secao 4.1).
NOTE_KEYS = ("start", "end", "midi", "syllable_id", "line_id", "text", "style")


def _syllables(analysis: dict[str, Any]) -> list[tuple[dict, dict]]:
    return [
        (line, syl)
        for line in analysis.get("lines", [])
        for word in line.get("words", [])
        for syl in word.get("syllables", [])
    ]


def anchor_notes(
    raw_notes: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Casa cada nota com a silaba de maior sobreposicao temporal.

    Devolve (notas ancoradas, quantidade de notas orfas). Orfa e nota que nao
    sobrepoe silaba nenhuma — descartada e contada, nunca chutada na mais proxima.
    """
    syls = _syllables(analysis)
    out: list[dict[str, Any]] = []
    orphans = 0

    for note in raw_notes:
        melhor: tuple[dict, dict] | None = None
        melhor_ov = 0.0
        for line, syl in syls:
            ov = min(note["end"], syl["end"]) - max(note["start"], syl["start"])
            if ov > melhor_ov:
                melhor_ov = ov
                melhor = (line, syl)

        if melhor is None:
            orphans += 1
            continue

        line, syl = melhor
        out.append({
            "start": round(float(note["start"]), 4),
            "end": round(float(note["end"]), 4),
            "midi": int(note["midi"]),
            "syllable_id": syl["syllable_id"],
            "line_id": syl["line_id"],
            "text": syl["text"],
            "style": line.get("style", ""),
        })

    return out, orphans
```

- [ ] **Step 4: Rodar o teste e verificar que passa**

```bash
python -m pytest tests/test_melody_anchor.py -v
```

Esperado: PASS, 7 testes.

- [ ] **Step 5: Verificar o controle negativo de verdade**

Trocar `if ov > melhor_ov:` por `if ov >= melhor_ov:` (aceita sobreposição zero) e rodar:

```bash
python -m pytest tests/test_melody_anchor.py -v
```

Esperado: **FAIL** em `test_CONTROLE_NEGATIVO_encosto_sem_sobreposicao_nao_ancora`.
Desfazer e confirmar verde.

- [ ] **Step 6: Commit**

```bash
git add scripts/melody_anchor.py tests/test_melody_anchor.py
git commit -m "feat: ancoragem de notas cantadas nas silabas do analysis.json"
```

---

### Task 4: Estágio `scripts/s05b_melody.py`

**Depende da Task 0** (schema real do ROSVOT) e da Task 3 (`anchor_notes`).

**Files:**
- Create: `scripts/s05b_melody.py`
- Test: `tests/test_melody_stage.py`
- Read: `docs/superpowers/plans/assets/rosvot-schema.md` (da Task 0)

**Interfaces:**
- Consumes: `anchor_notes(raw_notes, analysis) -> (notes, orphans)` da Task 3.
- Produces:
  - `rosvot_to_notes(raw: Any) -> list[dict]` — normaliza a saída bruta do ROSVOT para
    itens `{start, end, midi}`. **É a única função do projeto que conhece o formato do
    ROSVOT.**
  - `build_melody(raw: Any, analysis: dict, source: str) -> dict` — o documento
    `melody.json` completo.
  - CLI: `python scripts/s05b_melody.py --job-dir <path>`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_melody_stage.py`. **Ajustar `_raw_rosvot()` para o schema real
registrado em `docs/superpowers/plans/assets/rosvot-schema.md`** — o exemplo abaixo assume
`{"note_start","note_end","note_pitch"}` e precisa casar com a realidade medida.

```python
import json
import tempfile
import unittest
from pathlib import Path

from scripts.s05b_melody import build_melody, rosvot_to_notes


def _raw_rosvot():
    """AJUSTAR para o schema real da Task 0 antes de implementar."""
    return {"note_start": [1.05, 3.10], "note_end": [1.45, 3.30], "note_pitch": [62, 60]}


def _analysis():
    return {
        "lines": [
            {
                "text": "la", "start": 1.0, "end": 2.0, "style": "chorus",
                "words": [{
                    "word": "la", "start": 1.0, "end": 2.0, "id": "L001_W001",
                    "syllables": [{
                        "syllable_id": "L001_W001_S001", "line_id": "L001",
                        "word_id": "L001_W001", "text": "la", "start": 1.0, "end": 1.5,
                    }],
                }],
            },
            {
                "text": "vai", "start": 3.0, "end": 4.0, "style": "rap",
                "words": [{
                    "word": "vai", "start": 3.0, "end": 4.0, "id": "L002_W001",
                    "syllables": [{
                        "syllable_id": "L002_W001_S001", "line_id": "L002",
                        "word_id": "L002_W001", "text": "vai", "start": 3.0, "end": 3.4,
                    }],
                }],
            },
        ]
    }


class RosvotParserTests(unittest.TestCase):
    def test_normaliza_para_start_end_midi(self):
        notes = rosvot_to_notes(_raw_rosvot())
        self.assertEqual(len(notes), 2)              # cardinalidade primeiro
        self.assertEqual(set(notes[0]), {"start", "end", "midi"})
        self.assertAlmostEqual(notes[0]["start"], 1.05)
        self.assertEqual(notes[0]["midi"], 62)

    def test_CONTROLE_NEGATIVO_saida_vazia_estoura(self):
        with self.assertRaises(ValueError):
            rosvot_to_notes({"note_start": [], "note_end": [], "note_pitch": []})

    def test_CONTROLE_NEGATIVO_schema_desconhecido_estoura(self):
        with self.assertRaises(ValueError):
            rosvot_to_notes({"coisa": "que o ROSVOT nunca devolveu"})


class BuildMelodyTests(unittest.TestCase):
    def test_documento_tem_o_contrato_da_spec(self):
        doc = build_melody(_raw_rosvot(), _analysis(), source="rosvot")
        self.assertEqual(doc["source"], "rosvot")
        self.assertEqual(len(doc["notes"]), 2)
        self.assertEqual(doc["orphans"], 0)
        self.assertEqual(
            set(doc["notes"][0]),
            {"start", "end", "midi", "syllable_id", "line_id", "text", "style"},
        )

    def test_CONTROLE_NEGATIVO_zero_notas_ancoradas_estoura(self):
        # Notas em 40 s, analysis so tem linha ate 4 s: nada ancora.
        raw = {"note_start": [40.0], "note_end": [40.5], "note_pitch": [62]}
        with self.assertRaises(ValueError):
            build_melody(raw, _analysis(), source="rosvot")

    def test_toda_nota_cai_dentro_de_alguma_linha(self):
        doc = build_melody(_raw_rosvot(), _analysis(), source="rosvot")
        spans = [(l["start"], l["end"]) for l in _analysis()["lines"]]
        self.assertGreater(len(doc["notes"]), 0)
        for n in doc["notes"]:
            dentro = any(min(n["end"], b) - max(n["start"], a) > 0 for a, b in spans)
            self.assertTrue(dentro, f"nota fora de qualquer linha: {n}")


class FixtureRealTests(unittest.TestCase):
    def test_fixture_real_do_rosvot_parseia(self):
        fx = Path("tests/fixtures/rosvot_publi_raw.json")
        if not fx.exists():
            self.skipTest("fixture da Task 0 ausente")
        notes = rosvot_to_notes(json.loads(fx.read_text(encoding="utf-8")))
        self.assertGreater(len(notes), 0)
        for n in notes:
            self.assertLess(n["start"], n["end"])
            self.assertGreaterEqual(n["midi"], 21)
            self.assertLessEqual(n["midi"], 108)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

```bash
python -m pytest tests/test_melody_stage.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'scripts.s05b_melody'`.

- [ ] **Step 3: Implementar o mínimo**

Criar `scripts/s05b_melody.py`. Ajustar `rosvot_to_notes` ao schema real da Task 0 —
o corpo abaixo cobre as duas formas mais prováveis e **estoura em vez de adivinhar**
quando não reconhece:

```python
"""Stage 05b — Melodia alvo do jogo de karaoke.

Roda o ROSVOT sobre vocals.wav, ancora as notas nas silabas do analysis.json e
escreve melody.json (contrato da spec secao 4.1).

O jogo nunca fala com o ROSVOT: fala com melody.json. Trocar o produtor mexe
apenas em rosvot_to_notes() e no campo "source".
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.melody_anchor import anchor_notes

logger = logging.getLogger(__name__)

MIDI_MIN, MIDI_MAX = 21, 108


def rosvot_to_notes(raw: Any) -> list[dict[str, Any]]:
    """Normaliza a saida bruta do ROSVOT para [{start, end, midi}].

    Unica funcao do projeto que conhece o formato do ROSVOT. Ver
    docs/superpowers/plans/assets/rosvot-schema.md para o schema medido.
    """
    notes: list[dict[str, Any]] = []

    if isinstance(raw, dict) and "note_start" in raw:
        starts, ends = raw["note_start"], raw["note_end"]
        pitches = raw.get("note_pitch") or raw.get("note_midi")
        if pitches is None:
            raise ValueError("ROSVOT: dict sem note_pitch/note_midi")
        if not (len(starts) == len(ends) == len(pitches)):
            raise ValueError(
                f"ROSVOT: tamanhos divergentes — start {len(starts)}, "
                f"end {len(ends)}, pitch {len(pitches)}"
            )
        notes = [
            {"start": float(s), "end": float(e), "midi": int(round(float(p)))}
            for s, e, p in zip(starts, ends, pitches)
        ]
    elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
        for item in raw:
            start = item.get("start", item.get("onset"))
            end = item.get("end", item.get("offset"))
            pitch = item.get("midi", item.get("pitch", item.get("note")))
            if start is None or end is None or pitch is None:
                raise ValueError(f"ROSVOT: item sem start/end/pitch: {item!r}")
            notes.append({
                "start": float(start),
                "end": float(end),
                "midi": int(round(float(pitch))),
            })
    else:
        raise ValueError(
            "ROSVOT: schema nao reconhecido. Registre o formato real em "
            "docs/superpowers/plans/assets/rosvot-schema.md e ajuste rosvot_to_notes()."
        )

    if not notes:
        raise ValueError("ROSVOT devolveu zero notas — sem cardinalidade nao ha melodia")

    fora = [n for n in notes if not (MIDI_MIN <= n["midi"] <= MIDI_MAX)]
    if fora:
        raise ValueError(
            f"ROSVOT: {len(fora)} de {len(notes)} notas fora da faixa MIDI "
            f"{MIDI_MIN}-{MIDI_MAX}; provavel unidade errada (Hz em vez de MIDI)"
        )
    return notes


def build_melody(raw: Any, analysis: dict[str, Any], source: str) -> dict[str, Any]:
    raw_notes = rosvot_to_notes(raw)
    notes, orphans = anchor_notes(raw_notes, analysis)
    if not notes:
        raise ValueError(
            f"nenhuma das {len(raw_notes)} notas ancorou em silaba — "
            "alinhamento ou unidade de tempo errada"
        )
    return {
        "source": source,
        "generated_at": int(time.time()),
        "orphans": orphans,
        "raw_note_count": len(raw_notes),
        "notes": notes,
    }


def rosvot_command(vocals: Path, out_json: Path) -> list[str]:
    """Comando de inferencia do ROSVOT.

    AJUSTAR ao comando real registrado na Task 0 em
    docs/superpowers/plans/assets/rosvot-schema.md. Este e o unico ponto do
    projeto que sabe onde o ROSVOT mora.
    """
    return [
        str(Path("vendor/ROSVOT/.venv/Scripts/python.exe")),
        str(Path("vendor/ROSVOT/infer.py")),
        "--audio", str(vocals),
        "--out", str(out_json),
    ]


def run_rosvot(vocals: Path, out_json: Path) -> None:
    cmd = rosvot_command(vocals, out_json)
    logger.info("ROSVOT: %s", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"ROSVOT falhou ({proc.returncode}): {proc.stderr[-2000:]}")
    if not out_json.exists():
        raise RuntimeError(f"ROSVOT terminou sem escrever {out_json}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 05b — melodia alvo do jogo.")
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--source", default="rosvot")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    job_dir: Path = args.job_dir.resolve()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(job_dir / "pipeline.log", mode="a")],
        force=True,
    )

    vocals = job_dir / "vocals.wav"
    analysis_path = job_dir / "analysis.json"
    for p in (vocals, analysis_path):
        if not p.exists():
            logger.error("arquivo obrigatorio ausente: %s", p)
            return 1

    raw_path = job_dir / "rosvot_raw.json"
    run_rosvot(vocals, raw_path)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    doc = build_melody(raw, analysis, source=args.source)

    out = job_dir / "melody.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "melody.json: %d notas ancoradas de %d brutas, %d orfas",
        len(doc["notes"]), doc["raw_note_count"], doc["orphans"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**`rosvot_command()` é o único ponto que a Task 0 preenche** — o corpo acima é um chute
plausível e quase certamente errado no detalhe. Substituir pelo comando exato medido no
Step 2 da Task 0.

- [ ] **Step 4: Rodar o teste e verificar que passa**

```bash
python -m pytest tests/test_melody_stage.py -v
```

Esperado: PASS. Se `rosvot_to_notes` estourar na fixture real, o schema assumido no teste
não bate com o medido — corrigir o teste **e** a função pelo documento da Task 0.

- [ ] **Step 5: Verificar o controle negativo de verdade**

Trocar `if not notes: raise ValueError(...)` (em `rosvot_to_notes`) por `pass` e rodar:

```bash
python -m pytest tests/test_melody_stage.py -v
```

Esperado: **FAIL** em `test_CONTROLE_NEGATIVO_saida_vazia_estoura`. Desfazer e confirmar verde.

- [ ] **Step 6: Rodar de verdade na Publi**

```bash
python scripts/s05b_melody.py --job-dir jobs/publi-bet
python -c "
import json
d = json.load(open('jobs/publi-bet/melody.json', encoding='utf-8'))
print('notas ancoradas: %d de %d brutas' % (len(d['notes']), d['raw_note_count']))
print('orfas: %d de %d' % (d['orphans'], d['raw_note_count']))
dur = [n['end'] - n['start'] for n in d['notes']]
print('notas >= 100ms: %d de %d' % (sum(1 for x in dur if x >= 0.100), len(dur)))
rap = sum(1 for n in d['notes'] if n['style'] == 'rap')
print('notas em linha rap: %d de %d' % (rap, len(d['notes'])))
"
```

Anotar os quatro números com seus denominadores — eles vão para o relatório da Task 9.

- [ ] **Step 7: Commit**

```bash
git add scripts/s05b_melody.py tests/test_melody_stage.py
git commit -m "feat: estagio s05b gera melody.json a partir do ROSVOT"
```

---

### Task 5: Registrar o estágio no pipeline

**Files:**
- Modify: `scripts/pipeline_runner.py` (dentro de `build_stage_plan`, após o `Stage("analyzing", ...)` que hoje está em `scripts/pipeline_runner.py:127-133`)
- Test: `tests/test_pipeline_runner.py` (adicionar caso)

**Interfaces:**
- Consumes: `scripts/s05b_melody.py --job-dir <path>` da Task 4.
- Produces: um `Stage` chamado `"melody"` no plano, com `progress=55`.

- [ ] **Step 1: Escrever o teste que falha**

Adicionar em `tests/test_pipeline_runner.py`:

```python
def test_plano_inclui_estagio_melody_depois_de_analyzing(self):
    from pathlib import Path
    from scripts.pipeline_runner import build_stage_plan

    stages = build_stage_plan(Path("jobs/x"), "single-style-kf", "python")
    nomes = [s.name for s in stages]
    self.assertGreater(len(nomes), 0)                 # cardinalidade primeiro
    self.assertIn("melody", nomes)
    self.assertIn("analyzing", nomes)
    self.assertGreater(
        nomes.index("melody"), nomes.index("analyzing"),
        "melody precisa do analysis.json, tem que vir depois",
    )
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

```bash
python -m pytest tests/test_pipeline_runner.py -v -k melody
```

Esperado: FAIL com `'melody' not found in [...]`.

- [ ] **Step 3: Implementar o mínimo**

Em `scripts/pipeline_runner.py`, dentro do `stages.extend([...])` que hoje adiciona
`"aligning"` e `"analyzing"`, acrescentar um terceiro item logo após o `Stage("analyzing", ...)`:

```python
            Stage(
                "melody",
                [py, str(scripts_dir / "s05b_melody.py"), "--job-dir", str(job_dir)],
                55,
                timeout=1800 + _BUFFER_S,
            ),
```

- [ ] **Step 4: Rodar os testes e verificar que passam**

```bash
python -m pytest tests/test_pipeline_runner.py tests/test_pipeline_stage_contracts.py -v
```

Esperado: PASS. Se `test_pipeline_stage_contracts.py` tiver uma lista fixa de estágios
esperados, adicionar `"melody"` lá também.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_runner.py tests/test_pipeline_runner.py
git commit -m "feat: registra estagio melody no plano do pipeline"
```

---

### Task 6: Rotas Flask

**Files:**
- Modify: `server.py` (adicionar após `job_audio`, que termina em `server.py:1461`)
- Test: `tests/test_game_server.py`

**Interfaces:**
- Consumes: `melody.json` escrito pela Task 4.
- Produces:
  - `GET /job/<job_id>/melody.json` → 200 com o JSON, ou 404 com mensagem contendo o
    comando exato para gerar.
  - `GET /job/<job_id>/game` → 200 renderizando `game.html` (Task 7).

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_game_server.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._optional_imports import import_or_skip

import_or_skip("flask")
import server


def _write_job(job_dir: Path, job_id: str, *, com_melodia: bool) -> None:
    job_dir.mkdir(parents=True)
    (job_dir / "meta.json").write_text(json.dumps({
        "job_id": job_id, "song_name": "Publi de Bet", "preset": "single-style-kf",
        "created_at": 1, "duration_s": 176.2, "has_lyrics": True, "source": "zip",
    }), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps({
        "stage": "done", "progress": 100, "error": "", "updated_at": 1,
    }), encoding="utf-8")
    (job_dir / "instrumental.wav").write_bytes(b"RIFF")
    if com_melodia:
        (job_dir / "melody.json").write_text(json.dumps({
            "source": "rosvot", "generated_at": 1, "orphans": 0, "raw_note_count": 1,
            "notes": [{
                "start": 1.0, "end": 1.5, "midi": 62,
                "syllable_id": "L001_W001_S001", "line_id": "L001",
                "text": "la", "style": "chorus",
            }],
        }), encoding="utf-8")


class GameRoutesTests(unittest.TestCase):
    def test_melody_json_e_servido_quando_existe(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_job(Path(tmp) / "publi-bet", "publi-bet", com_melodia=True)
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                r = server.app.test_client().get("/job/publi-bet/melody.json")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.get_data(as_text=True))
        self.assertGreater(len(data["notes"]), 0)      # cardinalidade primeiro
        self.assertEqual(data["notes"][0]["syllable_id"], "L001_W001_S001")

    def test_CONTROLE_NEGATIVO_melody_ausente_da_404_com_o_comando(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_job(Path(tmp) / "publi-bet", "publi-bet", com_melodia=False)
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                r = server.app.test_client().get("/job/publi-bet/melody.json")
        self.assertEqual(r.status_code, 404)
        self.assertIn("s05b_melody.py", r.get_data(as_text=True))

    def test_CONTROLE_NEGATIVO_job_inexistente_da_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                r = server.app.test_client().get("/job/nao-existe/melody.json")
        self.assertEqual(r.status_code, 404)

    def test_CONTROLE_NEGATIVO_job_id_com_travessia_da_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                r = server.app.test_client().get("/job/..%2F..%2Fetc/melody.json")
        self.assertEqual(r.status_code, 404)

    def test_pagina_do_jogo_renderiza_e_referencia_os_modulos(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_job(Path(tmp) / "publi-bet", "publi-bet", com_melodia=True)
            with patch.object(server, "JOBS_DIR", Path(tmp)):
                r = server.app.test_client().get("/job/publi-bet/game")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("game.js", html)
        self.assertIn("publi-bet", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

```bash
python -m pytest tests/test_game_server.py -v
```

Esperado: FAIL com 404 onde se espera 200 (as rotas não existem).

- [ ] **Step 3: Implementar o mínimo**

Em `server.py`, logo após a função `job_audio`:

```python
_MELODY_CMD = "python scripts/s05b_melody.py --job-dir jobs/{job_id}"


@app.route("/job/<job_id>/melody.json")
def job_melody(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Not found", 404
    path = job_dir / "melody.json"
    if not path.exists():
        return (
            "melody.json ausente para este job. Gere com:\n  "
            + _MELODY_CMD.format(job_id=job_id),
            404,
            {"Content-Type": "text/plain; charset=utf-8"},
        )
    return send_file(path, mimetype="application/json", conditional=True)


@app.route("/job/<job_id>/game")
def job_game(job_id: str):
    try:
        job_dir = resolve_job_dir(JOBS_DIR, job_id)
    except ValueError:
        return "Job not found", 404
    if not job_dir.exists():
        return "Job not found", 404
    meta = json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    return render_template(
        "game.html",
        meta=meta,
        job_id=job_id,
        has_melody=(job_dir / "melody.json").exists(),
        has_instrumental=(job_dir / "instrumental.wav").exists(),
        melody_command=_MELODY_CMD.format(job_id=job_id),
    )
```

- [ ] **Step 4: Rodar o teste e verificar que passa**

```bash
python -m pytest tests/test_game_server.py -v
```

Esperado: os quatro testes de `melody.json` passam; o teste da página falha até a Task 7
criar `templates/game.html`. Isso é esperado — deixar falhando e seguir.

- [ ] **Step 5: Verificar o controle negativo de travessia**

Trocar `resolve_job_dir(JOBS_DIR, job_id)` por `JOBS_DIR / job_id` na rota `job_melody`
e rodar:

```bash
python -m pytest tests/test_game_server.py -v -k travessia
```

Esperado: **FAIL** — sem `resolve_job_dir` o job_id com `../` escapa da pasta de jobs.
Desfazer e confirmar verde. Esta é validação em fronteira de confiança: não pode ser
simplificada.

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_game_server.py
git commit -m "feat: rotas melody.json e game no servidor"
```

---

### Task 7: Tela e glue (`templates/game.html` + `static/game.js`)

**Files:**
- Create: `templates/game.html`
- Create: `static/game.js`
- Test: `tests/test_game_server.py` (o teste da página, escrito na Task 6, passa aqui)

**Interfaces:**
- Consumes: `detectPitch`, `decimate` (Task 2); `scorePitchNote`, `scoreRhythmNote`,
  `finalScore`, `grade`, `comboMultiplier` (Task 1); `GET /job/<id>/melody.json` e
  `GET /job/<id>/audio/<stem>` (Task 6 e `server.py:1448`).
- Produces: nada consumido por outra task. É a ponta da cadeia.

**Regra de ouro desta task:** `game.js` não contém regra de pontuação. Se aparecer um
`0.25`, um `12 * Math.log2` ou um `± 1 semitom` dentro dele, a regra está no lugar errado.

- [ ] **Step 1: Criar o template**

Criar `templates/game.html` seguindo o padrão dos templates existentes (ver
`templates/job.html` para o `{% extends %}` correto):

```html
{% extends "base.html" %}
{% block content %}
<section id="game" data-job-id="{{ job_id }}"
         data-has-melody="{{ '1' if has_melody else '0' }}"
         data-has-instrumental="{{ '1' if has_instrumental else '0' }}"
         data-melody-command="{{ melody_command }}">

  <h1>{{ meta.song_name }}</h1>

  <div id="screen-setup">
    <label>Voz guia
      <input id="guide-gain" type="range" min="0" max="100" value="35">
      <output id="guide-gain-out">35%</output>
    </label>
    <label>Velocidade
      <select id="rate">
        <option value="0.25">0.25x</option>
        <option value="0.5">0.5x</option>
        <option value="0.75">0.75x</option>
        <option value="1" selected>1x</option>
        <option value="1.5">1.5x</option>
        <option value="2">2x</option>
      </select>
    </label>
    <label>Latencia
      <input id="latency" type="range" min="-200" max="200" value="0">
      <output id="latency-out">0 ms</output>
    </label>
    <p>Teste o microfone: <strong id="mic-note">—</strong></p>
    <p id="leak-warning" hidden></p>
    <p id="fatal" hidden></p>
    <button id="btn-start" type="button">Comecar</button>
  </div>

  <div id="screen-play" hidden>
    <canvas id="stage" width="1280" height="420"></canvas>
    <p id="line-current"></p>
    <p id="line-next"></p>
    <p>Pontos <output id="score">0</output> · Combo <output id="combo">0</output>
       · <span id="track-label"></span></p>
    <label>Voz guia <input id="guide-gain-live" type="range" min="0" max="100" value="35"></label>
    <label>Latencia <input id="latency-live" type="range" min="-200" max="200" value="0"></label>
  </div>

  <div id="screen-result" hidden>
    <h2><output id="result-grade"></output> — <output id="result-percent"></output></h2>
    <p>Maior combo: <output id="result-combo"></output></p>
    <ol id="result-lines"></ol>
  </div>

  <audio id="a-instrumental" src="/job/{{ job_id }}/audio/instrumental" preload="auto"></audio>
  <audio id="a-vocals"       src="/job/{{ job_id }}/audio/vocals"       preload="auto"></audio>
</section>
<script type="module" src="/static/game.js"></script>
{% endblock %}
```

- [ ] **Step 2: Rodar o teste da página e verificar que passa**

```bash
python -m pytest tests/test_game_server.py -v -k pagina
```

Esperado: PASS. Se falhar por bloco inexistente, abrir `templates/base.html` e usar o
nome de bloco que ele define.

- [ ] **Step 3: Escrever o glue**

Criar `static/game.js`:

```javascript
// Glue do jogo: relogio, playback, captura e desenho. Nenhuma regra de pontuacao
// mora aqui — elas estao em game-scoring.js, testadas fora do navegador.
import { detectPitch, decimate } from './game-pitch.js';
import { scorePitchNote, scoreRhythmNote, finalScore, grade, hzToMidi } from './game-scoring.js';

const el = (id) => document.getElementById(id);
const root = el('game');
const JOB = root.dataset.jobId;

const PITCH_MIN_S = 0.100;   // abaixo disso a nota vai para a pista de ritmo
const WINDOW_S    = 4.0;     // janela visivel de notas rolando
const FFT_SIZE    = 2048;

const fatal = (msg) => { const p = el('fatal'); p.hidden = false; p.textContent = msg;
                         el('btn-start').disabled = true; };

if (root.dataset.hasMelody !== '1') fatal(`Melodia nao gerada. Rode: ${root.dataset.melodyCommand}`);
if (root.dataset.hasInstrumental !== '1') fatal('Este job nao tem instrumental.wav.');
if (!navigator.mediaDevices?.getUserMedia) fatal('Este navegador nao expoe getUserMedia.');

const aInstr = el('a-instrumental');
const aVocal = el('a-vocals');
let ctx, analyser, buf, gainVocal, melody = null, frames = [], results = [];
let combo = 0, pontos = 0, rafId = null, latencyS = 0;

function espelhar(a, b, aplicar) {
  const sync = (v) => { a.value = v; b.value = v; aplicar(Number(v)); };
  a.addEventListener('input', () => sync(a.value));
  b.addEventListener('input', () => sync(b.value));
  sync(a.value);
}

async function preparar() {
  const r = await fetch(`/job/${JOB}/melody.json`);
  if (!r.ok) { fatal(await r.text()); return false; }
  melody = await r.json();
  if (!melody.notes?.length) { fatal('melody.json sem notas.'); return false; }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false },
    });
  } catch {
    fatal('Microfone negado. Libere o acesso e recarregue.');
    return false;
  }

  ctx = new AudioContext();
  analyser = ctx.createAnalyser();
  analyser.fftSize = FFT_SIZE;
  buf = new Float32Array(analyser.fftSize);
  ctx.createMediaStreamSource(stream).connect(analyser);

  gainVocal = ctx.createGain();
  ctx.createMediaElementSource(aVocal).connect(gainVocal).connect(ctx.destination);
  ctx.createMediaElementSource(aInstr).connect(ctx.destination);

  latencyS = (ctx.outputLatency || 0) + (ctx.baseLatency || 0);
  el('latency').value = el('latency-live').value = Math.round(latencyS * 1000);
  el('latency-out').textContent = `${Math.round(latencyS * 1000)} ms`;

  espelhar(el('guide-gain'), el('guide-gain-live'), (v) => {
    gainVocal.gain.value = v / 100;
    el('guide-gain-out').textContent = `${v}%`;
  });
  espelhar(el('latency'), el('latency-live'), (v) => {
    latencyS = v / 1000;
    el('latency-out').textContent = `${v} ms`;
  });

  el('rate').addEventListener('change', () => {
    const v = Number(el('rate').value);
    for (const a of [aInstr, aVocal]) { a.preservesPitch = true; a.playbackRate = v; }
  });

  medirMic();
  return true;
}

// Amostra o pitch no mesmo instante do quadro desenhado.
function amostrar(tempoMusica) {
  analyser.getFloatTimeDomainData(buf);
  const fator = Math.max(1, Math.round(ctx.sampleRate / 16000));
  const p = detectPitch(decimate(buf, fator), ctx.sampleRate / fator);
  if (p) frames.push({ t: tempoMusica, hz: p.hz, clarity: p.clarity });
  return p;
}

function medirMic() {
  const tick = () => {
    if (!ctx) return;
    const p = amostrar(0);
    el('mic-note').textContent = p ? `${p.hz.toFixed(0)} Hz` : '—';
    if (el('screen-setup').hidden === false) requestAnimationFrame(tick);
  };
  tick();
}

function tocar() {
  el('screen-setup').hidden = true;
  el('screen-play').hidden = false;
  frames = []; results = []; combo = 0; pontos = 0;
  aVocal.currentTime = aInstr.currentTime = 0;
  aInstr.play(); aVocal.play();
  setInterval(() => {
    if (Math.abs(aVocal.currentTime - aInstr.currentTime) > 0.03) {
      aVocal.currentTime = aInstr.currentTime;
    }
  }, 1000);
  rafId = requestAnimationFrame(laco);
}

let proxima = 0;
function laco() {
  const t = aInstr.currentTime - latencyS;
  amostrar(t);

  while (proxima < melody.notes.length && melody.notes[proxima].end < t) {
    const n = melody.notes[proxima];
    const ritmo = n.style === 'rap' || (n.end - n.start) < PITCH_MIN_S;
    const score = ritmo ? scoreRhythmNote(frames, n) : scorePitchNote(frames, n.midi, n);
    results.push({ score, max: ritmo ? 50 : 100 });
    combo = score >= 50 ? combo + 1 : 0;
    pontos += score;
    el('score').value = Math.round(pontos);
    el('combo').value = combo;
    el('track-label').textContent = ritmo ? 'RITMO' : 'AFINACAO';
    proxima += 1;
  }

  desenhar(t);

  if (aInstr.ended || proxima >= melody.notes.length) { terminar(); return; }
  rafId = requestAnimationFrame(laco);
}

function desenhar(t) {
  const cv = el('stage'), g = cv.getContext('2d');
  g.clearRect(0, 0, cv.width, cv.height);
  const x = (tempo) => ((tempo - t) / WINDOW_S) * cv.width + cv.width * 0.2;
  const y = (midi) => cv.height - ((midi % 12) / 12) * cv.height;

  for (const n of melody.notes) {
    if (n.end < t - 1 || n.start > t + WINDOW_S) continue;
    g.fillStyle = n.style === 'rap' ? '#888' : '#4af';
    g.fillRect(x(n.start), y(n.midi) - 8, Math.max(2, x(n.end) - x(n.start)), 16);
  }
  g.fillStyle = '#f70';
  for (const f of frames) {
    if (f.t < t - 1 || f.t > t) continue;
    g.fillRect(x(f.t), y(hzToMidi(f.hz)) - 2, 3, 4);
  }
  g.strokeStyle = '#fff';
  g.beginPath(); g.moveTo(x(t), 0); g.lineTo(x(t), cv.height); g.stroke();

  const atual = melody.notes[Math.min(proxima, melody.notes.length - 1)];
  el('line-current').textContent = atual ? atual.text : '';
}

function terminar() {
  cancelAnimationFrame(rafId);
  aInstr.pause(); aVocal.pause();
  el('screen-play').hidden = true;
  el('screen-result').hidden = false;
  if (results.length === 0) { el('result-grade').value = '—'; return; }
  const out = finalScore(results);
  el('result-grade').value = grade(out.percent);
  el('result-percent').value = `${Math.round(out.percent * 100)}%`;
  el('result-combo').value = out.maxCombo;
}

el('btn-start').addEventListener('click', async () => {
  if (!ctx && !(await preparar())) return;
  tocar();
});
```

- [ ] **Step 4: Verificar no navegador**

```bash
python server.py
```

Abrir `http://localhost:5000/job/publi-bet/game`. Confirmar, um por um: a nota do
microfone aparece ao cantar; o botão inicia; as barras rolam; o traço laranja acompanha
a voz; a tela de resultado aparece no fim.

- [ ] **Step 5: Verificar o controle negativo da tela de erro**

```bash
mv jobs/publi-bet/melody.json jobs/publi-bet/melody.json.bak
```

Recarregar a página: deve aparecer o comando de geração e o botão desabilitado, **não**
uma tela em branco nem erro só no console. Restaurar:

```bash
mv jobs/publi-bet/melody.json.bak jobs/publi-bet/melody.json
```

- [ ] **Step 6: Commit**

```bash
git add templates/game.html static/game.js
git commit -m "feat: tela do jogo com playback, captura e render em canvas"
```

---

### Task 8: Os três auxiliares (`static/game-assist.js`)

**Files:**
- Create: `static/game-assist.js`
- Test: `tests/game-assist.test.mjs`
- Modify: `static/game.js` (ligar os três)

**Interfaces:**
- Consumes: `foldSemitone`, `hzToMidi` (Task 1).
- Produces:
  - `bestOffset(micOnsets: number[], noteOnsets: number[], maxOffsetS = 0.3) -> number`
  - `isLeaking(rmsFrames: number[], threshold = 0.02) -> boolean`
  - `suggestTranspose(errors: number[], minSamples = 8) -> number | null`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/game-assist.test.mjs`:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { bestOffset, isLeaking, suggestTranspose } from '../static/game-assist.js';

test('bestOffset acha um atraso constante de 120 ms', () => {
  const notas = [1.0, 2.0, 3.0, 4.0];
  const mic   = notas.map((t) => t + 0.12);
  assert.ok(Math.abs(bestOffset(mic, notas) - 0.12) < 0.02);
});

test('bestOffset acha adiantamento de 80 ms', () => {
  const notas = [1.0, 2.0, 3.0, 4.0];
  const mic   = notas.map((t) => t - 0.08);
  assert.ok(Math.abs(bestOffset(mic, notas) + 0.08) < 0.02);
});

test('CONTROLE NEGATIVO bestOffset: sem onsets de mic devolve 0', () => {
  assert.equal(bestOffset([], [1.0, 2.0]), 0);
});

test('CONTROLE NEGATIVO bestOffset: sem notas devolve 0', () => {
  assert.equal(bestOffset([1.0], []), 0);
});

test('isLeaking: energia alta no silencio acusa vazamento', () => {
  assert.equal(isLeaking([0.08, 0.09, 0.07]), true);
});

test('CONTROLE NEGATIVO isLeaking: sala quieta nao acusa', () => {
  assert.equal(isLeaking([0.001, 0.002, 0.001]), false);
});

test('CONTROLE NEGATIVO isLeaking: lista vazia nao acusa nem afirma', () => {
  assert.equal(isLeaking([]), false);
});

test('suggestTranspose: desvio estavel de -2 semitons e sugerido', () => {
  const erros = [-2.1, -1.9, -2.0, -2.05, -1.95, -2.0, -2.1, -1.9];
  assert.equal(suggestTranspose(erros), -2);
});

test('CONTROLE NEGATIVO suggestTranspose: poucas amostras nao sugere', () => {
  assert.equal(suggestTranspose([-2, -2, -2]), null);
});

test('CONTROLE NEGATIVO suggestTranspose: erro espalhado nao sugere', () => {
  const erros = [-3, 2, -1, 4, 0, -4, 3, 1];
  assert.equal(suggestTranspose(erros), null);
});

test('CONTROLE NEGATIVO suggestTranspose: afinado nao sugere', () => {
  assert.equal(suggestTranspose([0.1, -0.2, 0.05, 0, 0.1, -0.1, 0.2, 0]), null);
});
```

- [ ] **Step 2: Rodar o teste e verificar que falha**

```bash
node --test tests/game-assist.test.mjs
```

Esperado: FAIL com `Cannot find module '../static/game-assist.js'`.

- [ ] **Step 3: Implementar o mínimo**

Criar `static/game-assist.js`:

```javascript
// Tres auxiliares de mundo real: latencia, vazamento de microfone e tom do cantor.
// Todos puros — a decisao de aplicar e do usuario, na interface.

export const LEAK_THRESHOLD = 0.02;
export const TRANSPOSE_MIN_SAMPLES = 8;
export const TRANSPOSE_MAX_SPREAD = 1.0;   // semitons de desvio absoluto mediano

// Desloca os onsets do microfone ate casarem com os das notas. Devolve segundos:
// positivo = o audio do jogador chega atrasado.
export function bestOffset(micOnsets, noteOnsets, maxOffsetS = 0.3) {
  if (!micOnsets?.length || !noteOnsets?.length) return 0;
  const passo = 0.005;
  let melhor = 0, melhorCusto = Infinity;
  for (let off = -maxOffsetS; off <= maxOffsetS; off += passo) {
    let custo = 0;
    for (const m of micOnsets) {
      let d = Infinity;
      for (const n of noteOnsets) d = Math.min(d, Math.abs(m - off - n));
      custo += d;
    }
    if (custo < melhorCusto) { melhorCusto = custo; melhor = off; }
  }
  return Math.round(melhor * 1000) / 1000;
}

// Energia captada durante um trecho em que o jogador deveria estar calado.
export function isLeaking(rmsFrames, threshold = LEAK_THRESHOLD) {
  if (!rmsFrames?.length) return false;   // conjunto vazio nao acusa nem inocenta
  const media = rmsFrames.reduce((a, b) => a + b, 0) / rmsFrames.length;
  return media > threshold;
}

const mediana = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

// Desvio constante e estavel -> sugere transpor o alvo. Sugere, nunca aplica:
// aplicar sozinho transformaria desafinacao consistente em nota cheia.
export function suggestTranspose(errors, minSamples = TRANSPOSE_MIN_SAMPLES) {
  if (!errors?.length || errors.length < minSamples) return null;
  const med = mediana(errors);
  const espalhamento = mediana(errors.map((e) => Math.abs(e - med)));
  if (espalhamento > TRANSPOSE_MAX_SPREAD) return null;   // errou pra todo lado
  const semitons = Math.round(med);
  return semitons === 0 ? null : semitons;
}
```

- [ ] **Step 4: Rodar o teste e verificar que passa**

```bash
node --test tests/game-assist.test.mjs
```

Esperado: PASS, 11 testes.

- [ ] **Step 5: Verificar o controle negativo de verdade**

Trocar `if (espalhamento > TRANSPOSE_MAX_SPREAD) return null;` por `if (false) return null;`
e rodar:

```bash
node --test tests/game-assist.test.mjs
```

Esperado: **FAIL** em "erro espalhado nao sugere". Desfazer e confirmar verde.

- [ ] **Step 6: Ligar os três no `static/game.js`**

No topo, junto dos outros imports:

```javascript
import { bestOffset, isLeaking, suggestTranspose } from './game-assist.js';
import { foldSemitone, hzToMidi } from './game-scoring.js';
```

**Vazamento** — dentro de `preparar()`, logo após `medirMic()`, medir 2 s com o
instrumental tocando baixo e o jogador calado:

```javascript
  const rms = [];
  aInstr.play();
  await new Promise((ok) => {
    const t0 = performance.now();
    const tick = () => {
      analyser.getFloatTimeDomainData(buf);
      let e = 0;
      for (let i = 0; i < buf.length; i++) e += buf[i] * buf[i];
      rms.push(Math.sqrt(e / buf.length));
      if (performance.now() - t0 < 2000) requestAnimationFrame(tick); else ok();
    };
    tick();
  });
  aInstr.pause(); aInstr.currentTime = 0;
  if (isLeaking(rms)) {
    const p = el('leak-warning');
    p.hidden = false;
    p.textContent = 'Estou ouvindo a musica pelo seu microfone. Use fone ou baixe a voz guia.';
  }
```

**Calibração** — em `laco()`, acumular onsets e oferecer o offset uma única vez após a
primeira linha:

```javascript
// no escopo do modulo:
let micOnsets = [], noteOnsets = [], calibrado = false, ultimaClarity = 0;

// dentro de laco(), logo apos amostrar(t):
const ultimo = frames[frames.length - 1];
if (ultimo && ultimo.t === t) {
  if (ultimaClarity <= 0.5) micOnsets.push(t);   // silencio -> voz e um ataque
  ultimaClarity = ultimo.clarity;
} else {
  ultimaClarity = 0;
}

// dentro do while que fecha notas, junto de results.push(...):
noteOnsets.push(n.start);

// depois do while:
if (!calibrado && noteOnsets.length >= 4 && micOnsets.length >= 4) {
  calibrado = true;
  const off = bestOffset(micOnsets, noteOnsets);
  if (Math.abs(off) > 0.03 &&
      confirm(`Seu audio parece ${Math.round(off * 1000)} ms deslocado. Aplicar?`)) {
    latencyS += off;
    el('latency').value = el('latency-live').value = Math.round(latencyS * 1000);
  }
}
```

**Transposição** — acumular o erro por nota de afinação e oferecer uma vez:

```javascript
// no escopo do modulo:
let erros = [], transposeOferecido = false, transpose = 0;

// dentro do while, no ramo de afinacao (antes de calcular score):
const janela = frames.filter((f) => f.t >= n.start + 0.04 && f.t <= n.end && f.clarity > 0.5);
if (janela.length) {
  const med = janela.map((f) => foldSemitone(hzToMidi(f.hz) - (n.midi + transpose)));
  erros.push(med.reduce((a, b) => a + b, 0) / med.length);
}

// depois do while:
if (!transposeOferecido && erros.length >= 8) {
  transposeOferecido = true;
  const s = suggestTranspose(erros);
  if (s !== null && confirm(`Voce esta ${s} semitons do alvo. Transpor a musica?`)) {
    transpose = s;
  }
}
```

E no cálculo do score de afinação, usar `n.midi + transpose` em vez de `n.midi`.

- [ ] **Step 7: Verificar no navegador**

```bash
python server.py
```

Em `http://localhost:5000/job/publi-bet/game`: com fone, o aviso de vazamento **não**
aparece; tocando a música pelo alto-falante, ele **aparece**. Esse par é o controle
negativo — só um dos dois lados não prova nada.

- [ ] **Step 8: Commit**

```bash
git add static/game-assist.js tests/game-assist.test.mjs static/game.js
git commit -m "feat: calibracao de latencia, deteccao de vazamento e transposicao ofertada"
```

---

### Task 9: Prova de campo na Publi

**Files:**
- Create: `docs/superpowers/plans/assets/publi-field-report.md`

**Interfaces:**
- Consumes: tudo.
- Produces: o relatório que fecha o loop.

- [ ] **Step 1: Rodar a suíte inteira**

```bash
node --test tests/game-scoring.test.mjs tests/game-pitch.test.mjs tests/game-assist.test.mjs
```

```bash
python -m pytest tests/test_melody_anchor.py tests/test_melody_stage.py tests/test_game_server.py tests/test_pipeline_runner.py -v
```

Copiar as contagens exatas de cada corrida — "N de M passaram", nunca só "passou".

- [ ] **Step 2: Medir a melodia da Publi com denominador**

```bash
python -c "
import json
d = json.load(open('jobs/publi-bet/melody.json', encoding='utf-8'))
an = json.load(open('jobs/publi-bet/analysis.json', encoding='utf-8'))
notes = d['notes']
assert len(notes) > 0, 'zero notas: sem cardinalidade nao ha veredito'
span = sum(l['end'] - l['start'] for l in an['lines'])
cob = sum(n['end'] - n['start'] for n in notes)
afinacao = [n for n in notes if n['style'] != 'rap' and n['end'] - n['start'] >= 0.100]
print('notas ancoradas: %d de %d brutas' % (len(notes), d['raw_note_count']))
print('orfas:           %d de %d' % (d['orphans'], d['raw_note_count']))
print('cobertura:       %.1f s de %.1f s de span de linha' % (cob, span))
print('pista afinacao:  %d de %d notas' % (len(afinacao), len(notes)))
print('pista ritmo:     %d de %d notas' % (len(notes) - len(afinacao), len(notes)))
"
```

A soma das duas pistas tem que fechar com o total de notas. Se não fechar, há um bug de
classificação — não publicar o número antes de reconciliar.

- [ ] **Step 3: Jogar o refrão**

```bash
python server.py
```

Em `http://localhost:5000/job/publi-bet/game`: cantar o refrão inteiro com fone. Anotar a
porcentagem, a letra e o maior combo. Depois cantar **de propósito** uma terça acima e
confirmar que a pontuação cai — se cantar errado der a mesma nota, o jogo não está medindo
nada.

- [ ] **Step 4: Escrever o relatório**

Criar `docs/superpowers/plans/assets/publi-field-report.md` com: as contagens de teste com
denominador, os cinco números do Step 2, e o resultado das duas partidas do Step 3 (certa
e desafinada de propósito), lado a lado.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/assets/publi-field-report.md
git commit -m "docs: prova de campo do jogo de karaoke na Publi"
```

---

## Cobertura da spec

| Requisito da spec | Task |
| --- | --- |
| §4.1 contrato `melody.json` | 3, 4 |
| §4.2 estágio produtor | 4, 5 |
| §4.3 rotas | 6 |
| §5.1 arquivos do frontend | 1, 2, 7, 8 |
| §5.2 captura de microfone | 7 (com o desvio documentado acima) |
| §5.3 playback, slider de guia, velocidade, watchdog | 7 |
| §6 pontuação em duas pistas | 1, 7 |
| §7.1 duas pistas | 1, 7 |
| §7.2 calibração automática de latência | 8 |
| §7.3 detecção de vazamento | 8 |
| §7.4 transposição ofertada | 8 |
| §8 três telas e telas de erro | 7 |
| §9 provas e controles negativos | todas |
| §10 Etapa 0 antes de tudo | 0 |
