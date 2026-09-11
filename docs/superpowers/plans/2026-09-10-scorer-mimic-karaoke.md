# Scorer de imitação e canto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pontuar a gravação de um jogador contra uma referência em duas modalidades (imitar som cru e cantar trecho com letra alinhada), com um único scorer, numa página local de um jogador e uma rodada.

**Architecture:** Os dois modos convergem para a mesma estrutura intermediária `ReferenceTrack` (onsets + contorno de f0 em semitons). Muda só a fábrica que a produz. O scorer compara **forma relativa** — semitons centrados na mediana do próprio take, intervalos entre ataques, contagem de ataques — nunca alinhamento absoluto, o que o torna imune à latência de captura do navegador.

**Tech Stack:** Python 3.11 (env `karaoke_env`), Flask 3.1.3, numpy 1.26.4, scipy 1.17.1, librosa 0.11.0 (`pyin`), soundfile 0.13.1, ffmpeg 8.1 (PATH), pytest 9.0.2, HTML/JS sem build.

Spec: [`docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md`](../specs/2026-09-10-scorer-mimic-karaoke-design.md)

## Global Constraints

Valem para **toda** tarefa. Os requisitos de cada tarefa incluem esta seção implicitamente.

- **Zero dependência nova.** Tudo já está no `karaoke_env`. Se uma tarefa parecer exigir `pip install`, pare e reporte — não instale.
- **Interpretador**: `C:\Users\Katz\miniforge3\envs\karaoke_env\python.exe`. Os testes rodam com `python -m pytest` a partir da raiz do worktree.
- **CPU apenas.** `torch.cuda.is_available()` é `False` nesta máquina. `librosa.pyin` custa **5,5s para 60s de áudio** (medido); um take de 10s custa ~1s.
- **Nada de I/O em `karaoke/`**: os módulos em `karaoke/` são lógica pura, sem `subprocess` e sem leitura de arquivo, no molde de `karaoke/qc.py`. Leitura de disco e chamada de ffmpeg vivem na rota Flask e nos scripts.
- **Denominador junto do número**: toda estrutura de saída que reporta contagem reporta também o total sobre o qual a conta foi feita.
- **Cardinalidade antes do veredito**: `n_frames_compared == 0` é **falha**, nunca sucesso. Cheque sobre conjunto vazio é verde universal.
- **Controle negativo não é etapa opcional.** Nenhuma tarefa está pronta se a sua cerca nunca foi vista vermelha.
- **O pipeline não é tocado.** Nenhuma tarefa modifica `run_pipeline.py`, `scripts/*` ou `karaoke/paths.py`.
- Constantes de calibração ficam nomeadas no topo do módulo, nunca embutidas em expressão.

### Valores medidos em protótipo (2026-09-10) que as tarefas vão reproduzir

| grandeza | valor |
|---|---|
| onsets detectados em fixture de 5 bursts | 5 de 5, erro máximo 0,030s |
| `pyin` em fixture de 5 bursts (220–330Hz) | 58 de 111 frames voiced, f0 220–337Hz |
| identidade | melody 100,0 · rhythm 100,0 · attacks 100,0 · **total 100,0** |
| transposto +5 semitons | **total 100,0** |
| embaralhado no tempo | melody 34,6 · rhythm 0,0 · attacks 100,0 · **total 35,6** |
| clipe diferente | melody 0,0 · rhythm 0,0 · attacks 60,0 · **total 12,0** |
| baseline aleatório (n=30, seed 7) | média 24,6 · **p95 49,5** · max 57,9 |
| tolerância de ritmo resultante | 0,210s no material sintético; piso 0,050s no modo karaoke |

**As três relações inegociáveis:** `identidade ≈ transposto` (diferença ≤ 5), `identidade > embaralhado > clipe diferente`, `identidade > p95(acaso)`. Acaso é distribuição, não piso: nota ruim ficar abaixo do p95 é correto.

---

## File Structure

| arquivo | responsabilidade |
|---|---|
| `karaoke/onset.py` (novo) | RMS por janela e detecção de ataques. Sem I/O. |
| `karaoke/scorer.py` (novo) | `ReferenceTrack`, `ScoreReport`, as duas fábricas e `score()`. Sem I/O. |
| `karaoke/audio_fixtures.py` (novo) | Gerador de áudio sintético determinístico, usado pelos testes das duas tarefas seguintes. Sem I/O. |
| `server_score_addendum.py` (novo, raiz) | Rota `POST /api/score`: upload, ffmpeg, resolução de referência, validação. Molde: `server_preview_addendum.py`. |
| `web/mimic.html` (novo) | Página de uma rodada: toca referência, grava mic, mostra notas. |
| `tests/test_onset.py` (novo) | Cerca do detector de ataques. |
| `tests/test_scorer.py` (novo) | Os cinco controles. |
| `tests/test_score_route.py` (novo) | Cerca da validação de fronteira da rota. |
| `server.py` (modificar, 1 linha de registro) | Registra a rota do adendo. |

`karaoke/onset.py` duplica deliberadamente as três funções de `scripts/08_onset_dtw.py` (`compute_rms`, `detect_onsets` e suas constantes). Motivo: o script começa com dígito e não é importável sem `importlib`, e o spec proíbe tocar o pipeline no marco A. A duplicação leva comentário `ponytail:` nomeando a dívida e o caminho de colapso.

---

### Task 1: `karaoke/onset.py` — detecção de ataques

**Files:**
- Create: `karaoke/onset.py`
- Test: `tests/test_onset.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `WIN_MS: int = 25`, `HOP_MS: int = 10`, `ONSET_THRESHOLD: float = 0.008`, `MIN_GAP_S: float = 0.08`, `ENERGY_MIN: float = 0.02`
  - `compute_rms(samples: np.ndarray, sr: int) -> tuple[np.ndarray, float]` — devolve `(rms, frame_dur_s)`
  - `detect_onsets(rms: np.ndarray, frame_dur: float) -> np.ndarray` — devolve array de instantes em segundos

- [ ] **Step 1: Write the failing test**

Crie `tests/test_onset.py`:

```python
import numpy as np
import pytest

from karaoke.onset import compute_rms, detect_onsets

SR = 16000


def _bursts(times, freqs, dur=0.25, sr=SR):
    """Bursts senoidais com ataque seco — verdade de terreno conhecida."""
    total = max(times) + dur + 0.3
    out = np.zeros(int(total * sr), dtype=np.float32)
    for t, f in zip(times, freqs):
        i0 = int(t * sr)
        k = int(dur * sr)
        tt = np.arange(k) / sr
        env = np.minimum(1.0, np.exp(-3 * tt) + 0.15)
        out[i0:i0 + k] += (0.6 * env * np.sin(2 * np.pi * f * tt)).astype(np.float32)
    return np.clip(out, -1, 1)


def test_detecta_todos_os_ataques_conhecidos():
    times = [0.3, 0.9, 1.5, 2.4, 3.0]
    audio = _bursts(times, [220, 247, 262, 294, 330])

    rms, frame_dur = compute_rms(audio, SR)
    onsets = detect_onsets(rms, frame_dur)

    # denominador junto do numero
    assert len(onsets) == len(times), (
        f"detectou {len(onsets)} de {len(times)} ataques esperados: {onsets}"
    )
    erro_max = max(min(abs(o - t) for t in times) for o in onsets)
    assert erro_max <= 0.035, f"erro maximo {erro_max:.3f}s acima de 0.035s"


def test_silencio_nao_produz_ataque():
    """Controle negativo: sem energia nao ha ataque, e zero aqui e o resultado CORRETO."""
    audio = np.zeros(int(2.0 * SR), dtype=np.float32)
    rms, frame_dur = compute_rms(audio, SR)
    onsets = detect_onsets(rms, frame_dur)
    assert len(onsets) == 0, f"silencio gerou {len(onsets)} ataques"


def test_gap_minimo_funde_ataques_colados():
    """Dois bursts a 0.04s (abaixo de MIN_GAP_S=0.08) contam como um."""
    audio = _bursts([0.5, 0.54], [300, 300], dur=0.1)
    rms, frame_dur = compute_rms(audio, SR)
    onsets = detect_onsets(rms, frame_dur)
    assert len(onsets) == 1, f"esperava 1 ataque fundido, veio {len(onsets)}: {onsets}"


def test_cardinalidade_do_rms():
    """Um audio de 1s a hop de 10ms tem ~100 frames; zero seria falha silenciosa."""
    audio = _bursts([0.1], [300], dur=0.5)
    rms, frame_dur = compute_rms(audio, SR)
    assert len(rms) > 50, f"apenas {len(rms)} frames de RMS — populacao vazia nao valida nada"
    assert frame_dur == pytest.approx(0.010, abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karaoke.onset'`

- [ ] **Step 3: Write minimal implementation**

Crie `karaoke/onset.py`:

```python
"""
onset.py — Deteccao de ataques (onsets) por energia. Logica pura.
No subprocess, no file I/O.

ponytail: estas tres funcoes e suas constantes sao uma copia deliberada de
scripts/08_onset_dtw.py (linhas 15-21 e 31-55). Motivo: aquele modulo comeca com
digito e nao e importavel sem importlib, e o marco A do scorer nao pode tocar o
pipeline. Caminho de colapso: quando alguem proximo mexer em 08_onset_dtw.py,
trocar as definicoes de la por `from karaoke.onset import ...` e apagar esta nota.
"""
from __future__ import annotations

import numpy as np

WIN_MS = 25            # janela de analise
HOP_MS = 10            # passo entre janelas
ONSET_THRESHOLD = 0.008  # derivada minima do RMS para contar como ataque
MIN_GAP_S = 0.08       # gap minimo entre dois ataques
ENERGY_MIN = 0.02      # RMS minimo absoluto: evita ataque em ruido de fundo


def compute_rms(samples: np.ndarray, sr: int) -> tuple[np.ndarray, float]:
    """RMS janela a janela. Devolve (rms, duracao_do_frame_em_segundos)."""
    hop = int(sr * HOP_MS / 1000)
    win = int(sr * WIN_MS / 1000)
    rms = [
        float(np.sqrt(np.mean(samples[i:i + win] ** 2)))
        for i in range(0, len(samples) - win, hop)
    ]
    return np.asarray(rms, dtype=np.float64), hop / sr


def detect_onsets(rms: np.ndarray, frame_dur: float) -> np.ndarray:
    """Ataque = derivada do RMS acima do limiar, com energia suficiente e
    respeitando o gap minimo desde o ataque anterior."""
    if len(rms) < 2:
        return np.empty(0, dtype=np.float64)
    drms = np.diff(rms)
    onsets: list[float] = []
    last = -1.0
    for i, d in enumerate(drms):
        t = i * frame_dur
        if d > ONSET_THRESHOLD and rms[i + 1] > ENERGY_MIN and (t - last) > MIN_GAP_S:
            onsets.append(t)
            last = t
    return np.asarray(onsets, dtype=np.float64)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_onset.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Ver a cerca vermelha (controle negativo obrigatório)**

Sabote `ONSET_THRESHOLD = 0.008` para `0.8` em `karaoke/onset.py`, rode
`python -m pytest tests/test_onset.py -v`, e confirme que
`test_detecta_todos_os_ataques_conhecidos` **falha** com 0 de 5 ataques.
Depois restaure `0.008` e rode de novo para confirmar 4 passed.
Se a sabotagem não deixar nenhum teste vermelho, a cerca não existe: pare e reporte.

- [ ] **Step 6: Commit**

```bash
git add karaoke/onset.py tests/test_onset.py
git commit -m "feat(scorer): deteccao de ataques por energia, com cerca"
```

---

### Task 2: `karaoke/audio_fixtures.py` + `ReferenceTrack`

**Files:**
- Create: `karaoke/audio_fixtures.py`, `karaoke/scorer.py`
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `karaoke.onset.compute_rms`, `karaoke.onset.detect_onsets`
- Produces:
  - `karaoke.audio_fixtures.bursts(times: list[float], freqs: list[float], dur: float = 0.25, sr: int = 16000) -> np.ndarray`
  - `karaoke.audio_fixtures.SR: int = 16000`
  - `karaoke.scorer.MELODY_POINTS: int = 200`, `MIN_VOICED_FRAMES: int = 10`, `F0_MIN_HZ: float = 65.0`, `F0_MAX_HZ: float = 1000.0`
  - `karaoke.scorer.ReferenceTrack` — dataclass com `onsets: np.ndarray`, `semitones: np.ndarray`, `frame_dur: float`, `duration: float`, `n_voiced: int`, `n_frames: int`, `n_octave_suspect: int`
  - `karaoke.scorer.track_from_audio(samples: np.ndarray, sr: int) -> ReferenceTrack`

- [ ] **Step 1: Write the failing test**

Crie `tests/test_scorer.py`:

```python
import numpy as np
import pytest

from karaoke.audio_fixtures import SR, bursts
from karaoke.scorer import MIN_VOICED_FRAMES, track_from_audio

TIMES = [0.3, 0.9, 1.5, 2.4, 3.0]
FREQS = [220.0, 247.0, 262.0, 294.0, 330.0]


def test_track_extrai_ataques_e_contorno():
    track = track_from_audio(bursts(TIMES, FREQS), SR)

    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} esperados"
    )
    # cardinalidade: contorno vazio e FALHA, nao sucesso
    assert track.n_voiced >= MIN_VOICED_FRAMES, (
        f"apenas {track.n_voiced} frames voiced de {track.n_frames} — populacao insuficiente"
    )
    assert track.n_voiced <= track.n_frames, "voiced nao pode exceder o total de frames"
    assert len(track.semitones) == track.n_voiced
    assert track.duration == pytest.approx(len(bursts(TIMES, FREQS)) / SR, abs=0.01)


def test_contorno_centrado_na_mediana():
    """Mediana em zero e o que torna a nota agnostica a registro."""
    track = track_from_audio(bursts(TIMES, FREQS), SR)
    assert float(np.median(track.semitones)) == pytest.approx(0.0, abs=0.5)


def test_transposicao_nao_muda_o_contorno():
    base = track_from_audio(bursts(TIMES, FREQS), SR)
    alto = track_from_audio(bursts(TIMES, [f * 2 ** (5 / 12) for f in FREQS]), SR)

    n = min(len(base.semitones), len(alto.semitones))
    assert n >= MIN_VOICED_FRAMES, f"apenas {n} frames comparaveis"
    diff = float(np.mean(np.abs(base.semitones[:n] - alto.semitones[:n])))
    assert diff <= 1.0, f"contorno mudou {diff:.2f} semitons com transposicao de +5"


def test_conta_suspeita_de_erro_de_oitava():
    """Risco 2 do spec vira numero, nao promessa. Bursts limpos nao devem ter salto
    de oitava; o contador existe para o material real, onde e 4.9%."""
    track = track_from_audio(bursts(TIMES, FREQS), SR)
    assert track.n_voiced >= MIN_VOICED_FRAMES, f"{track.n_voiced} frames voiced"
    frac = track.n_octave_suspect / track.n_voiced
    assert frac <= 0.05, (
        f"{track.n_octave_suspect} de {track.n_voiced} frames com salto de oitava "
        f"({100 * frac:.1f}%) em fixture sintetica limpa"
    )


def test_silencio_nao_produz_contorno():
    """Controle negativo: audio mudo da populacao vazia, e isso deve ser visivel."""
    track = track_from_audio(np.zeros(int(2.0 * SR), dtype=np.float32), SR)
    assert len(track.onsets) == 0
    assert track.n_voiced < MIN_VOICED_FRAMES, (
        f"silencio gerou {track.n_voiced} frames voiced"
    )
    assert track.n_octave_suspect == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'karaoke.audio_fixtures'`

- [ ] **Step 3: Write minimal implementation**

Crie `karaoke/audio_fixtures.py`:

```python
"""
audio_fixtures.py — Gerador de audio sintetico determinístico para teste do scorer.
Logica pura. Mora em karaoke/ (nao em tests/) porque a rota e o notebook de
calibracao tambem o usam.
"""
from __future__ import annotations

import numpy as np

SR = 16000


def bursts(times: list[float], freqs: list[float], dur: float = 0.25,
           sr: int = SR) -> np.ndarray:
    """Sequencia de bursts senoidais com ataque seco e decaimento.

    Verdade de terreno conhecida: um ataque por instante em `times`, f0 igual ao
    `freqs` correspondente. E o que permite testar o scorer sem microfone.
    """
    if len(times) != len(freqs):
        raise ValueError(f"times ({len(times)}) e freqs ({len(freqs)}) diferem")
    if not times:
        raise ValueError("times vazio: fixture sem conteudo nao valida nada")
    total = max(times) + dur + 0.3
    out = np.zeros(int(total * sr), dtype=np.float32)
    for t, f in zip(times, freqs):
        i0 = int(t * sr)
        k = int(dur * sr)
        tt = np.arange(k) / sr
        env = np.minimum(1.0, np.exp(-3 * tt) + 0.15)
        out[i0:i0 + k] += (0.6 * env * np.sin(2 * np.pi * f * tt)).astype(np.float32)
    return np.clip(out, -1.0, 1.0)
```

Crie `karaoke/scorer.py`:

```python
"""
scorer.py — Pontuacao de imitacao e canto. Logica pura.
No subprocess, no file I/O.

Os dois modos do jogo (imitar som cru, cantar trecho com letra) convergem para
ReferenceTrack; score() nao sabe de qual modo o track veio.
"""
from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

from karaoke.onset import compute_rms, detect_onsets

# ── Knobs de calibracao ──────────────────────────────────────────────────────
MELODY_POINTS = 200        # contornos sao reamostrados para este tamanho comum
MIN_VOICED_FRAMES = 10     # abaixo disso nao ha contorno para comparar
F0_MIN_HZ = 65.0           # ~C2
F0_MAX_HZ = 1000.0         # ~B5


@dataclass
class ReferenceTrack:
    onsets: np.ndarray      # instantes de ataque, em segundos
    semitones: np.ndarray   # contorno de f0 em semitons centrado na mediana (so voiced)
    frame_dur: float
    duration: float
    n_voiced: int           # denominador do contorno
    n_frames: int           # total de frames analisados pelo pyin
    n_octave_suspect: int   # frames com |semitom| > 11: suspeita de erro de oitava do pyin


def track_from_audio(samples: np.ndarray, sr: int) -> ReferenceTrack:
    """Extrai ataques e contorno de f0 de um audio mono."""
    samples = np.asarray(samples, dtype=np.float32)
    rms, frame_dur = compute_rms(samples, sr)
    onsets = detect_onsets(rms, frame_dur)

    f0, voiced, _ = librosa.pyin(samples, fmin=F0_MIN_HZ, fmax=F0_MAX_HZ, sr=sr)
    n_frames = int(len(f0))
    vals = f0[voiced]
    n_voiced = int(len(vals))
    if n_voiced >= MIN_VOICED_FRAMES:
        semitones = 12.0 * np.log2(vals / np.nanmedian(vals))
    else:
        semitones = np.empty(0, dtype=np.float64)
    semitones = np.asarray(semitones, dtype=np.float64)

    # Risco declarado no spec: pyin erra oitava em voz cantada separada pelo Demucs.
    # Medido em 2026-09-10 no material real: 59 de 1207 frames voiced (4.9%). Nao
    # corrigimos a oitava aqui — contamos, para que o erro seja VISIVEL em vez de
    # silenciosamente embutido na nota.
    n_octave_suspect = int(np.sum(np.abs(semitones) > 11.0)) if len(semitones) else 0

    return ReferenceTrack(
        onsets=onsets,
        semitones=semitones,
        frame_dur=frame_dur,
        duration=len(samples) / sr,
        n_voiced=n_voiced,
        n_frames=n_frames,
        n_octave_suspect=n_octave_suspect,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Ver a cerca vermelha**

Troque `12.0 * np.log2(vals / np.nanmedian(vals))` por `12.0 * np.log2(vals / 440.0)`
(remove a centragem na mediana). Rode `python -m pytest tests/test_scorer.py -v` e
confirme que `test_contorno_centrado_na_mediana` **e** `test_transposicao_nao_muda_o_contorno`
ficam vermelhos. Restaure e confirme 4 passed.

- [ ] **Step 6: Commit**

```bash
git add karaoke/audio_fixtures.py karaoke/scorer.py tests/test_scorer.py
git commit -m "feat(scorer): ReferenceTrack com ataques e contorno de f0 centrado"
```

---

### Task 3: `score()` e os cinco controles

**Files:**
- Modify: `karaoke/scorer.py` (acrescenta `ScoreReport`, constantes de nota e `score()`)
- Test: `tests/test_scorer.py` (acrescenta os cinco controles)

**Interfaces:**
- Consumes: `karaoke.scorer.ReferenceTrack`, `track_from_audio`, `karaoke.audio_fixtures.bursts`
- Produces:
  - `karaoke.scorer.RHYTHM_TOL_RATIO: float = 0.35`, `RHYTHM_TOL_FLOOR_S: float = 0.050`, `WEIGHTS: dict[str, float]`
  - `karaoke.scorer.ScoreReport` — dataclass com `melody: float`, `rhythm: float`, `attacks: float`, `total: float`, `n_onsets_ref: int`, `n_onsets_take: int`, `n_frames_compared: int`, `rhythm_tol_s: float`
  - `karaoke.scorer.score(ref: ReferenceTrack, take: ReferenceTrack) -> ScoreReport`

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/test_scorer.py`:

```python
from karaoke.scorer import score

DIFERENTE_TIMES = [0.2, 1.7, 2.9]
DIFERENTE_FREQS = [440.0, 330.0, 392.0]
EMBARALHADO_TIMES = [0.3, 0.75, 1.9, 2.1, 3.1]
EMBARALHADO_FREQS = [FREQS[i] for i in (2, 0, 4, 1, 3)]


@pytest.fixture(scope="module")
def ref():
    return track_from_audio(bursts(TIMES, FREQS), SR)


def _total(ref_track, times, freqs):
    return score(ref_track, track_from_audio(bursts(times, freqs), SR))


def _baseline_aleatorio(ref_track, n=30, seed=7):
    """p95 do acaso. Sem esta regua, nenhuma nota alta significa nada."""
    rng = np.random.default_rng(seed)
    totais = []
    for _ in range(n):
        k = int(rng.integers(3, 7))
        t = np.sort(rng.uniform(0.2, 3.2, k)).tolist()
        f = rng.uniform(150.0, 500.0, k).tolist()
        totais.append(_total(ref_track, t, f).total)
    return np.asarray(totais)


# ── controle 1: identidade ───────────────────────────────────────────────────
def test_controle_1_identidade(ref):
    r = _total(ref, TIMES, FREQS)
    assert r.n_frames_compared > 0, "zero frames comparados e falha, nao sucesso"
    assert r.n_onsets_ref == r.n_onsets_take == len(TIMES)
    assert r.total >= 95.0, f"identidade deu {r.total:.1f} (esperado >= 95)"


# ── controle 4: transposto ───────────────────────────────────────────────────
def test_controle_4_transposto_mantem_melodia(ref):
    r = _total(ref, TIMES, [f * 2 ** (5 / 12) for f in FREQS])
    assert r.n_frames_compared > 0
    assert r.melody >= 85.0, f"melodia caiu para {r.melody:.1f} com +5 semitons"


# ── controle 3: embaralhado ──────────────────────────────────────────────────
def test_controle_3_embaralhado_derruba_ritmo(ref):
    r = _total(ref, EMBARALHADO_TIMES, EMBARALHADO_FREQS)
    ident = _total(ref, TIMES, FREQS)
    assert r.rhythm < 50.0, f"ritmo {r.rhythm:.1f} alto para take embaralhado"
    assert r.total < ident.total, (
        f"embaralhado ({r.total:.1f}) nao ficou abaixo da identidade ({ident.total:.1f})"
    )


# ── controle 2: clipe diferente ──────────────────────────────────────────────
def test_controle_2_clipe_diferente(ref):
    dif = _total(ref, DIFERENTE_TIMES, DIFERENTE_FREQS)
    emb = _total(ref, EMBARALHADO_TIMES, EMBARALHADO_FREQS)
    assert dif.total < emb.total, (
        f"clipe diferente ({dif.total:.1f}) deveria ficar abaixo do embaralhado ({emb.total:.1f})"
    )


# ── controle 5: baseline aleatorio e as relacoes exigidas ────────────────────
def test_controle_5_identidade_supera_o_acaso(ref):
    totais = _baseline_aleatorio(ref)
    assert len(totais) == 30, f"baseline examinou {len(totais)} amostras de 30"
    p95 = float(np.percentile(totais, 95))
    ident = _total(ref, TIMES, FREQS).total
    assert ident > p95, (
        f"identidade {ident:.1f} nao supera o p95 do acaso {p95:.1f} "
        f"(media do acaso {totais.mean():.1f})"
    )


def test_relacoes_de_ordem_completas(ref):
    """As tres relacoes inegociaveis do spec, num teste so, com os numeros a vista."""
    ident = _total(ref, TIMES, FREQS).total
    transp = _total(ref, TIMES, [f * 2 ** (5 / 12) for f in FREQS]).total
    emb = _total(ref, EMBARALHADO_TIMES, EMBARALHADO_FREQS).total
    dif = _total(ref, DIFERENTE_TIMES, DIFERENTE_FREQS).total
    p95 = float(np.percentile(_baseline_aleatorio(ref), 95))

    assert abs(ident - transp) <= 5.0, f"identidade {ident:.1f} vs transposto {transp:.1f}"
    assert ident > emb > dif, f"ordem quebrou: {ident:.1f} > {emb:.1f} > {dif:.1f}"
    assert ident > p95, f"identidade {ident:.1f} nao supera acaso p95 {p95:.1f}"


def test_take_sem_ataque_suficiente_nao_inventa_nota(ref):
    """Controle negativo: take mudo tem que dar nota baixa com denominador visivel."""
    r = score(ref, track_from_audio(np.zeros(int(2.0 * SR), dtype=np.float32), SR))
    assert r.n_onsets_take == 0, f"silencio gerou {r.n_onsets_take} ataques"
    assert r.n_frames_compared == 0, "sem contorno nao ha frames comparados"
    assert r.rhythm == 0.0 and r.melody == 0.0
    assert r.total < 25.0, f"take mudo recebeu {r.total:.1f}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: FAIL — `ImportError: cannot import name 'score' from 'karaoke.scorer'`

- [ ] **Step 3: Write minimal implementation**

Acrescente a `karaoke/scorer.py`, depois de `track_from_audio`:

```python
# ── Knobs de nota ────────────────────────────────────────────────────────────
# Tolerancia de ritmo RELATIVA ao intervalo mediano da referencia, com piso
# absoluto. Medido em 2026-09-10: no modo karaoke o intervalo mediano entre
# palavras e 0,140s, entao uma tolerancia absoluta de 200ms seria maior que o
# proprio intervalo medido e a nota de ritmo ficaria vazia.
RHYTHM_TOL_RATIO = 0.35
RHYTHM_TOL_FLOOR_S = 0.050
WEIGHTS = {"melody": 0.45, "rhythm": 0.35, "attacks": 0.20}


@dataclass
class ScoreReport:
    melody: float           # 0..100
    rhythm: float           # 0..100
    attacks: float          # 0..100
    total: float            # 0..100
    n_onsets_ref: int
    n_onsets_take: int
    n_frames_compared: int  # zero e FALHA, nao sucesso
    rhythm_tol_s: float     # tolerancia efetivamente usada, para auditoria


def _resample(contour: np.ndarray, n: int = MELODY_POINTS) -> np.ndarray:
    return np.interp(np.linspace(0.0, 1.0, n),
                     np.linspace(0.0, 1.0, len(contour)),
                     contour)


def score(ref: ReferenceTrack, take: ReferenceTrack) -> ScoreReport:
    """Compara forma relativa, nunca alinhamento absoluto: um atraso global
    constante na captura nao altera nota nenhuma."""
    n_ref, n_take = len(ref.onsets), len(take.onsets)

    # ataques: quanto as contagens batem
    attacks = 100.0 * max(0.0, 1.0 - abs(n_ref - n_take) / max(n_ref, n_take, 1))

    # ritmo: intervalos ENTRE ataques, nao instantes
    tol = RHYTHM_TOL_FLOOR_S
    if n_ref >= 2 and n_take >= 2:
        iv_ref = np.diff(ref.onsets)
        iv_take = np.diff(take.onsets)
        tol = max(RHYTHM_TOL_FLOOR_S, RHYTHM_TOL_RATIO * float(np.median(iv_ref)))
        k = min(len(iv_ref), len(iv_take))
        mad = float(np.mean(np.abs(iv_ref[:k] - iv_take[:k])))
        rhythm = 100.0 * max(0.0, 1.0 - mad / tol)
    else:
        rhythm = 0.0

    # melodia: correlacao dos contornos centrados, reamostrados a tamanho comum
    if len(ref.semitones) >= MIN_VOICED_FRAMES and len(take.semitones) >= MIN_VOICED_FRAMES:
        r = float(np.corrcoef(_resample(ref.semitones), _resample(take.semitones))[0, 1])
        melody = 0.0 if np.isnan(r) else 100.0 * max(0.0, r)
        n_frames_compared = MELODY_POINTS
    else:
        melody = 0.0
        n_frames_compared = 0

    total = (WEIGHTS["melody"] * melody
             + WEIGHTS["rhythm"] * rhythm
             + WEIGHTS["attacks"] * attacks)

    return ScoreReport(
        melody=melody, rhythm=rhythm, attacks=attacks, total=total,
        n_onsets_ref=n_ref, n_onsets_take=n_take,
        n_frames_compared=n_frames_compared, rhythm_tol_s=tol,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: PASS, 12 passed (5 da Task 2 + 7 desta)

Valores esperados, medidos em protótipo: identidade 100,0 · transposto 100,0 ·
embaralhado 35,6 · diferente 12,0 · acaso média 24,6 e p95 49,5.
Se um número divergir mas as **três relações** continuarem valendo, atualize o
limiar no teste para o valor medido e anote o novo número — os limiares são alvo
de calibração, as relações não.

- [ ] **Step 5: Ver a cerca vermelha**

Troque `np.median(iv_ref)` por `np.median(iv_take)` na tolerância — passa a calibrar
pelo take em vez da referência, o que premia take esticado. Rode
`python -m pytest tests/test_scorer.py -v` e confirme vermelho em
`test_controle_3_embaralhado_derruba_ritmo`. Restaure e confirme 12 passed.

- [ ] **Step 6: Commit**

```bash
git add karaoke/scorer.py tests/test_scorer.py
git commit -m "feat(scorer): score() com melodia, ritmo e ataques mais os cinco controles"
```

---

### Task 4: modo karaoke — referência a partir de `word_timing.json`

**Files:**
- Modify: `karaoke/scorer.py` (acrescenta `track_from_word_timing`)
- Test: `tests/test_scorer.py` (acrescenta 3 testes)

**Interfaces:**
- Consumes: `karaoke.scorer.ReferenceTrack`, `track_from_audio`
- Produces:
  - `karaoke.scorer.track_from_word_timing(words: list[dict], samples: np.ndarray, sr: int) -> ReferenceTrack`
  - Levanta `ValueError` se `words` for vazio ou se os `start` não forem monotônicos.

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `tests/test_scorer.py`:

```python
from karaoke.scorer import track_from_word_timing


def test_karaoke_usa_inicios_de_palavra_como_ataques():
    """Os ataques vem do gabarito, o contorno vem do audio."""
    words = [
        {"word": "um", "start": 0.30, "end": 0.55, "score": 1.0},
        {"word": "dois", "start": 0.90, "end": 1.15, "score": 1.0},
        {"word": "tres", "start": 1.50, "end": 1.75, "score": 1.0},
        {"word": "quatro", "start": 2.40, "end": 2.65, "score": 1.0},
        {"word": "cinco", "start": 3.00, "end": 3.25, "score": 1.0},
    ]
    audio = bursts(TIMES, FREQS)
    track = track_from_word_timing(words, audio, SR)

    assert len(track.onsets) == len(words), (
        f"{len(track.onsets)} ataques de {len(words)} palavras"
    )
    assert track.onsets[0] == pytest.approx(0.30)
    assert track.n_voiced >= MIN_VOICED_FRAMES, (
        f"{track.n_voiced} frames voiced de {track.n_frames}"
    )


def test_karaoke_gabarito_vazio_e_erro_nao_nota_zero():
    """Populacao vazia tem que explodir, nao virar nota. Zero itens nao e sucesso."""
    with pytest.raises(ValueError, match="vazio"):
        track_from_word_timing([], bursts(TIMES, FREQS), SR)


def test_karaoke_gabarito_fora_de_ordem_e_erro():
    words = [
        {"word": "um", "start": 1.00, "end": 1.20, "score": 1.0},
        {"word": "dois", "start": 0.50, "end": 0.70, "score": 1.0},
    ]
    with pytest.raises(ValueError, match="monot"):
        track_from_word_timing(words, bursts(TIMES, FREQS), SR)


def test_karaoke_pontua_contra_si_mesmo():
    """O take que reproduz o gabarito recebe nota alta — mesmo score() dos dois modos."""
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]
    audio = bursts(TIMES, FREQS)
    ref = track_from_word_timing(words, audio, SR)
    r = score(ref, track_from_audio(audio, SR))
    assert r.n_frames_compared > 0
    assert r.total >= 80.0, f"karaoke contra si mesmo deu {r.total:.1f}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: FAIL — `ImportError: cannot import name 'track_from_word_timing'`

- [ ] **Step 3: Write minimal implementation**

Acrescente a `karaoke/scorer.py`:

```python
def track_from_word_timing(words: list[dict], samples: np.ndarray,
                           sr: int) -> ReferenceTrack:
    """Referencia do modo karaoke: ataques vem do gabarito alinhado
    (work/jobs/<id>/05_alignment/word_timing.json), contorno vem do audio vocal.

    Precisao medida do gabarito em 2026-09-10: 66% das palavras a <=100ms de um
    ataque detectado, contra 47% do acaso. A nota herda esse erro — o modo karaoke
    e "melhor que acaso", nao "correto".
    """
    if not words:
        raise ValueError("word_timing vazio: gabarito sem palavras nao produz referencia")

    starts = np.asarray([float(w["start"]) for w in words], dtype=np.float64)
    if np.any(np.diff(starts) < 0):
        fora = int(np.sum(np.diff(starts) < 0))
        raise ValueError(
            f"word_timing nao e monotonico: {fora} de {len(starts) - 1} pares fora de ordem"
        )

    base = track_from_audio(samples, sr)
    return ReferenceTrack(
        onsets=starts,
        semitones=base.semitones,
        frame_dur=base.frame_dur,
        duration=base.duration,
        n_voiced=base.n_voiced,
        n_frames=base.n_frames,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scorer.py -v`
Expected: PASS, 16 passed

- [ ] **Step 5: Ver a cerca vermelha**

Remova o bloco `if np.any(np.diff(starts) < 0)`. Rode
`python -m pytest tests/test_scorer.py::test_karaoke_gabarito_fora_de_ordem_e_erro -v`
e confirme vermelho (`DID NOT RAISE`). Restaure e confirme 16 passed.

- [ ] **Step 6: Verificação contra dado real**

Run:
```bash
python -c "import json,sys; sys.path.insert(0,'.'); import soundfile as sf; from karaoke.scorer import track_from_word_timing, track_from_audio, score; w=json.load(open('work/jobs/mimic_gab_01/05_alignment/word_timing.mfa.json',encoding='utf-8')); a,sr=sf.read('work/jobs/mimic_gab_01/03_vocals_clean/vocals_raw.wav',dtype='float32'); ref=track_from_word_timing(w,a,sr); r=score(ref,track_from_audio(a,sr)); print(f'palavras={len(w)} onsets_ref={r.n_onsets_ref} frames={r.n_frames_compared} tol={r.rhythm_tol_s:.3f}s total={r.total:.1f}')"
```
Expected: `palavras=71 onsets_ref=71`, `frames=200`, `tol=0.050s` (piso, porque o
intervalo mediano real é 0,140s), e um `total` finito. Leva ~11s por causa dos dois
`pyin` em 60s de áudio. Se `frames=0`, pare: cardinalidade zero é falha.

- [ ] **Step 7: Commit**

```bash
git add karaoke/scorer.py tests/test_scorer.py
git commit -m "feat(scorer): modo karaoke com referencia vinda de word_timing.json"
```

---

### Task 5: rota `POST /api/score`

**Files:**
- Create: `server_score_addendum.py`
- Modify: `server.py` (uma linha de import e uma de registro, junto do registro de `server_preview_addendum`)
- Test: `tests/test_score_route.py`

**Interfaces:**
- Consumes: `karaoke.scorer.{track_from_audio, track_from_word_timing, score}`, `karaoke.paths.{word_timing_json, vocals_raw}` (somente leitura)
- Produces:
  - `server_score_addendum.MAX_UPLOAD_BYTES: int = 8 * 1024 * 1024`
  - `server_score_addendum.MODES: frozenset = frozenset({"mimic", "karaoke"})`
  - `server_score_addendum.REF_ID_RE` — `re.compile(r"^[A-Za-z0-9_-]{1,64}$")`
  - `server_score_addendum.make_score_route(app) -> None` — registra `POST /api/score`

- [ ] **Step 1: Write the failing test**

Crie `tests/test_score_route.py`:

```python
import io

import pytest
from flask import Flask

from server_score_addendum import MODES, REF_ID_RE, make_score_route


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    make_score_route(app)
    return app.test_client()


def test_modo_fora_da_lista_fechada_da_400(client):
    r = client.post("/api/score", data={
        "mode": "sabotagem",
        "ref": "mimic_gab_01",
        "take": (io.BytesIO(b"\x00" * 100), "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}"
    assert "mode" in r.get_json()["error"]


def test_ref_com_travessia_de_caminho_da_400(client):
    """Nunca interpolar ref em caminho: ../ tem que morrer na fronteira."""
    r = client.post("/api/score", data={
        "mode": "karaoke",
        "ref": "../../etc/passwd",
        "take": (io.BytesIO(b"\x00" * 100), "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "ref" in r.get_json()["error"]


def test_upload_ausente_da_400(client):
    r = client.post("/api/score", data={"mode": "mimic", "ref": "abc"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "take" in r.get_json()["error"]


def test_upload_grande_demais_da_413(client):
    from server_score_addendum import MAX_UPLOAD_BYTES
    grande = io.BytesIO(b"\x00" * (MAX_UPLOAD_BYTES + 1))
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (grande, "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 413, f"veio {r.status_code}"


def test_audio_indecodificavel_da_400_nao_500(client):
    """ffmpeg falhando e erro do cliente, nao estouro do servidor."""
    lixo = io.BytesIO(b"isto nao e audio" * 10)
    r = client.post("/api/score", data={
        "mode": "mimic", "ref": "abc", "take": (lixo, "take.webm"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400, f"veio {r.status_code}: {r.data[:200]}"


def test_lista_de_modos_e_fechada():
    assert MODES == frozenset({"mimic", "karaoke"})
    assert len(MODES) == 2, f"MODES tem {len(MODES)} entradas"


@pytest.mark.parametrize("mau", ["../x", "a/b", "x" * 65, "", "a;b", "a b"])
def test_regex_de_ref_rejeita_entradas_ruins(mau):
    assert REF_ID_RE.match(mau) is None, f"{mau!r} passou pela regex"


@pytest.mark.parametrize("bom", ["mimic_gab_01", "abc-123", "A", "x" * 64])
def test_regex_de_ref_aceita_entradas_boas(bom):
    assert REF_ID_RE.match(bom) is not None, f"{bom!r} foi rejeitado"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_score_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server_score_addendum'`

- [ ] **Step 3: Write minimal implementation**

Crie `server_score_addendum.py` na raiz:

```python
"""
server_score_addendum.py — Rota POST /api/score.
Molde: server_preview_addendum.py (funcao make_*_route(app) chamada pelo server.py).

Aqui vive todo o I/O do scorer: upload, ffmpeg, leitura de disco. karaoke/scorer.py
segue puro.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from flask import jsonify, request

from karaoke import paths as kpaths
from karaoke.scorer import score, track_from_audio, track_from_word_timing

MAX_UPLOAD_BYTES = 8 * 1024 * 1024          # take de uma rodada nao passa disso
MODES = frozenset({"mimic", "karaoke"})     # lista FECHADA
REF_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MIMIC_REF_DIR = Path("input") / "mimic_refs"


def _erro(msg: str, status: int):
    return jsonify({"error": msg}), status


def _webm_para_wav(src: Path, dst: Path) -> bool:
    """16k mono, mesmo padrao de scripts/03_vocal_cleaning.py — incluindo o mkdir
    do diretorio de saida, cuja ausencia foi bug real naquele script."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)],
        capture_output=True,
    )
    return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def make_score_route(app) -> None:
    @app.route("/api/score", methods=["POST"])
    def api_score():
        mode = (request.form.get("mode") or "").strip()
        if mode not in MODES:
            return _erro(f"mode invalido: esperado um de {sorted(MODES)}", 400)

        ref_id = (request.form.get("ref") or "").strip()
        if REF_ID_RE.match(ref_id) is None:
            return _erro("ref invalido: use [A-Za-z0-9_-], no maximo 64 caracteres", 400)

        upload = request.files.get("take")
        if upload is None:
            return _erro("take ausente: envie o audio gravado no campo 'take'", 400)

        blob = upload.read(MAX_UPLOAD_BYTES + 1)
        if len(blob) > MAX_UPLOAD_BYTES:
            return _erro(f"take maior que {MAX_UPLOAD_BYTES} bytes", 413)
        if not blob:
            return _erro("take vazio", 400)

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            src = tmpdir / "take.upload"
            src.write_bytes(blob)
            wav = tmpdir / "take.wav"
            if not _webm_para_wav(src, wav):
                return _erro("take nao pudemos decodificar como audio", 400)

            take_samples, sr = sf.read(wav, dtype="float32")
            if take_samples.ndim > 1:
                take_samples = take_samples.mean(axis=1)
            take = track_from_audio(take_samples, sr)

            if mode == "karaoke":
                wt = kpaths.word_timing_json(ref_id)
                vocals = kpaths.vocals_raw(ref_id)
                if not wt.exists() or not vocals.exists():
                    return _erro(f"job {ref_id} nao tem gabarito alinhado", 404)
                words = json.loads(wt.read_text(encoding="utf-8"))
                ref_samples, ref_sr = sf.read(vocals, dtype="float32")
                try:
                    ref = track_from_word_timing(words, ref_samples, ref_sr)
                except ValueError as exc:
                    return _erro(f"gabarito invalido: {exc}", 422)
            else:
                clip = MIMIC_REF_DIR / f"{ref_id}.wav"
                if not clip.exists():
                    return _erro(f"clipe de referencia {ref_id} nao existe", 404)
                ref_samples, ref_sr = sf.read(clip, dtype="float32")
                if ref_samples.ndim > 1:
                    ref_samples = ref_samples.mean(axis=1)
                ref = track_from_audio(ref_samples, ref_sr)

        report = score(ref, take)
        return jsonify({
            "melody": round(report.melody, 1),
            "rhythm": round(report.rhythm, 1),
            "attacks": round(report.attacks, 1),
            "total": round(report.total, 1),
            "n_onsets_ref": report.n_onsets_ref,
            "n_onsets_take": report.n_onsets_take,
            "n_frames_compared": report.n_frames_compared,
            "rhythm_tol_s": round(report.rhythm_tol_s, 4),
            "n_octave_suspect_ref": ref.n_octave_suspect,
            "n_voiced_ref": ref.n_voiced,
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_score_route.py -v`
Expected: PASS, 16 passed (os dois `parametrize` contam 6 e 4)

- [ ] **Step 5: Registrar no `server.py`**

Em `server.py`, na linha 28 (junto do import de `server_preview_addendum`), acrescente:

```python
from server_score_addendum import make_score_route
```

E logo após a criação do `app` (`server.py:40`), acrescente:

```python
make_score_route(app)
```

Run: `python -c "import server; print([str(r) for r in server.app.url_map.iter_rules() if 'score' in str(r)])"`
Expected: uma linha contendo `/api/score`

- [ ] **Step 6: Ver a cerca vermelha**

Troque a checagem `if mode not in MODES` por `if False`. Rode
`python -m pytest tests/test_score_route.py -v` e confirme vermelho em
`test_modo_fora_da_lista_fechada_da_400`. Faça o mesmo com a regex de `ref`
(troque por `if False`) e confirme vermelho em
`test_ref_com_travessia_de_caminho_da_400`. Restaure as duas e confirme 16 passed.
**Validação de fronteira sem cerca vermelha não conta como validação.**

- [ ] **Step 7: Commit**

```bash
git add server_score_addendum.py tests/test_score_route.py server.py
git commit -m "feat(scorer): rota POST /api/score com validacao de fronteira"
```

---

### Task 6: `web/mimic.html` — a página de uma rodada

**Files:**
- Create: `web/mimic.html`

**Interfaces:**
- Consumes: `POST /api/score` com `multipart/form-data` (`mode`, `ref`, `take`), resposta JSON com `melody`, `rhythm`, `attacks`, `total`, `n_onsets_ref`, `n_onsets_take`, `n_frames_compared`, `rhythm_tol_s`
- Produces: nada consumido por tarefa posterior.

- [ ] **Step 1: Escrever a página**

Crie `web/mimic.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Imite o som</title>
  <style>
    :root { color-scheme: light dark; }
    body { font: 16px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
    button { font: inherit; padding: .6rem 1.2rem; }
    button[aria-pressed="true"] { outline: 3px solid currentColor; }
    .notas { display: grid; grid-template-columns: repeat(2, 1fr); gap: .5rem 1rem; margin-top: 1.5rem; }
    .nota { border: 1px solid; padding: .5rem .75rem; }
    .nota b { display: block; font-size: 1.6rem; }
    .total { grid-column: 1 / -1; }
    .aud { font-size: .85rem; opacity: .8; margin-top: 1rem; }
    /* estado nunca depende so de cor: usa texto e simbolo */
    .estado { font-weight: 600; }
  </style>
</head>
<body>
  <h1>Imite o som</h1>

  <p>
    <label for="ref">Referência</label>
    <input id="ref" value="mimic_gab_01" size="24">
    <label for="mode">Modo</label>
    <select id="mode">
      <option value="karaoke">karaoke</option>
      <option value="mimic">mimic</option>
    </select>
  </p>

  <p><audio id="player" controls></audio></p>

  <p>
    <button id="rec" aria-pressed="false">● Gravar</button>
    <span id="estado" class="estado" role="status" aria-live="polite">Pronto.</span>
  </p>

  <div class="notas" id="notas" hidden>
    <div class="nota total">Total <b id="n-total">—</b></div>
    <div class="nota">Melodia <b id="n-melody">—</b></div>
    <div class="nota">Ritmo <b id="n-rhythm">—</b></div>
    <div class="nota">Ataques <b id="n-attacks">—</b></div>
  </div>

  <p class="aud" id="auditoria"></p>

<script>
const $ = (id) => document.getElementById(id);
const estado = $("estado");
let rec = null, chunks = [], gravando = false;

function diz(texto) { estado.textContent = texto; }

$("rec").addEventListener("click", async () => {
  if (gravando) {
    rec.stop();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    diz("Sem acesso ao microfone: " + e.name);
    return;
  }
  chunks = [];
  rec = new MediaRecorder(stream);
  rec.ondataavailable = (e) => chunks.push(e.data);
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    gravando = false;
    $("rec").textContent = "● Gravar";
    $("rec").setAttribute("aria-pressed", "false");
    diz("Pontuando…");

    const fd = new FormData();
    fd.append("mode", $("mode").value);
    fd.append("ref", $("ref").value);
    fd.append("take", new Blob(chunks, { type: "audio/webm" }), "take.webm");

    let r, data;
    try {
      r = await fetch("/api/score", { method: "POST", body: fd });
      data = await r.json();
    } catch (e) {
      diz("Falha de rede ao pontuar.");
      return;
    }
    if (!r.ok) {
      diz("Erro " + r.status + ": " + (data && data.error ? data.error : "desconhecido"));
      return;
    }
    $("n-total").textContent = data.total;
    $("n-melody").textContent = data.melody;
    $("n-rhythm").textContent = data.rhythm;
    $("n-attacks").textContent = data.attacks;
    $("notas").hidden = false;
    // denominador a vista: nota sem populacao examinada e opiniao com numero
    $("auditoria").textContent =
      `ataques: ${data.n_onsets_take} no take contra ${data.n_onsets_ref} na referência · ` +
      `${data.n_frames_compared} frames de contorno comparados · ` +
      `tolerância de ritmo ${data.rhythm_tol_s}s · ` +
      `oitava suspeita na referência: ${data.n_octave_suspect_ref} de ${data.n_voiced_ref} frames`;
    diz(data.n_frames_compared === 0
      ? "Atenção: nenhum frame de melodia foi comparado — a nota de melodia não vale."
      : "Pronto.");
  };
  rec.start();
  gravando = true;
  $("rec").textContent = "■ Parar";
  $("rec").setAttribute("aria-pressed", "true");
  diz("Gravando…");
});
</script>
</body>
</html>
```

- [ ] **Step 2: Subir o servidor**

Run: `python server.py`
Expected: log de inicialização sem traceback, incluindo a linha `Worker Python`.

- [ ] **Step 3: Verificação manual no navegador**

Abra `http://127.0.0.1:5000/static/mimic.html`. Com `mode=karaoke` e
`ref=mimic_gab_01`, grave 5 segundos falando ou cantando e confirme:

1. As quatro notas aparecem, todas entre 0 e 100.
2. A linha de auditoria mostra `71` ataques na referência (o gabarito tem 71 palavras)
   e `200` frames de contorno comparados.
3. O botão alterna entre `● Gravar` e `■ Parar`, e `aria-pressed` acompanha.
4. Negar a permissão do microfone mostra "Sem acesso ao microfone", não trava a página.

Este passo é manual de propósito: `MediaRecorder` e `getUserMedia` exigem gesto do
usuário e dispositivo real, e um teste automatizado disso precisaria de navegador
headless — fora do escopo do marco A.

- [ ] **Step 4: Rodar a suíte inteira**

Run: `python -m pytest tests/ --ignore=tests/test_critical_pipeline.py -q`
Expected: os 190 testes que já passavam **mais** os 36 novos (`test_onset.py` 4,
`test_scorer.py` 16 = 5+7+4 das Tasks 2/3/4, `test_score_route.py` 16) =
**226 passed**, 2 skipped, 1 xfailed, 7 errors.

Os 7 errors são pré-existentes e não seus: `tests/integration/test_pipeline_orchestrator.py`
faz mock de `run_pipeline.execute_external`, função que não existe no módulo. Se
aparecer um oitavo error, é seu — investigue antes de commitar.

`tests/test_critical_pipeline.py` fica fora porque ele fecha o stdout compartilhado e
envenena a contagem da suíte.

- [ ] **Step 5: Commit**

```bash
git add web/mimic.html
git commit -m "feat(scorer): pagina de uma rodada com captura de microfone"
```

---

## Notas de execução

**Ambiente.** Tudo roda no `karaoke_env`. Para os estágios que chamam `conda`, exporte
antes: `export PATH="/c/Users/Katz/miniforge3/Scripts:/c/Users/Katz/miniforge3/condabin:$PATH"`.
Nenhuma tarefa deste plano precisa disso — só a Task 4 Step 6 lê arquivos que o
pipeline já produziu.

**Se a Task 4 Step 6 não encontrar os arquivos**, o job `mimic_gab_01` não existe neste
worktree. Ele foi produzido em 2026-09-10 por:
`01_media_prep` → `02_vocal_isolation` → `03_vocal_cleaning` → `03_prepare_corpus` →
`04_mfa_alignment --lang en` → `05_mfa_to_json`, a partir de `input/test_1min/`.
`work/` é gitignored, então não viaja entre checkouts.

**Ordem das tarefas.** 1 → 2 → 3 → 4 → 5 → 6, nesta ordem. A Task 3 depende dos tipos da
Task 2; a Task 5 depende de `score()` da Task 3 e de `track_from_word_timing` da Task 4.
