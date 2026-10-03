# Cena reativa — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gerar um `background_scene.mp4` do tamanho da música, misturando 4 loops de uma cena conforme a energia do instrumental, e usá-lo no render final com a letra no topo.

**Architecture:** `karaoke/scene_score.py` (puro) transforma RMS + onsets em estados, pesos e ganho da fogueira por quadro. `karaoke/scene_compose.py` decodifica os loops, mistura em numpy e codifica por pipe do ffmpeg. `scripts/08c_scene_background.py` liga os dois a um job. `09_video_rendering.py` prefere o vídeo da cena e passa `legenda_topo` ao `build_render_cmd`.

**Tech Stack:** Python 3.11, numpy, ffmpeg/ffprobe 8.1 (sistema), pytest.

**Spec:** [docs/superpowers/specs/2026-09-30-cena-reativa-design.md](../specs/2026-09-30-cena-reativa-design.md)

## Global Constraints

- Estados na ordem fixa `CALMO=0, TENSAO=1, CLIMAX=2, ESCURO=3`; pesos sempre com 4 colunas nessa ordem.
- Limiares: tensão `0,45`/1 s/mín. 4 s em CALMO; clímax `0,75`/2 s/mín. 4 s em TENSÃO; dissipa `< 0,30`/3 s; queda `< 0,55`, mín. 3 s em CLÍMAX, teto 20 s; ESCURO fixo 2,5 s.
- Rampas: 1,2 s padrão; 0,6 s com alvo ESCURO; 2,0 s com alvo CALMO. Peso de tensão em TENSÃO: `0,4 + 0,6·e`.
- Fogueira: `ganho = 1 + 0,25·v`, `v` pulsa em 1 no onset e decai com constante de 0,3 s.
- Envelope: média móvel de 1,5 s; `e = clip((x − p10)/(p90 − p10), 0, 1)`; `p90 − p10 < 1e-6` → `e = 0`.
- Faixa da legenda no topo: `(0.05, 0.25)` da altura. Letra no topo = `force_style='Alignment=8'` no filtro `subtitles`.
- Pacote de cena em `input/scenes/<nome>/`: `calmo.mp4 tensao.mp4 climax.mp4 escuro.mp4 fogo_mask.png scene.json`.
- Nenhuma dependência nova. Sem PIL, sem matplotlib: imagem e vídeo entram e saem pelo ffmpeg.
- Rodar só os arquivos de teste afetados, em primeiro plano. **Nunca** `pytest` na suíte inteira: `test_critical_pipeline.py` fecha o stdout compartilhado e envenena os números.
- Linha de base medida antes do plano: `tests/test_render_cmd.py tests/test_bounce.py tests/test_teste_loop_fundo.py tests/test_paths_contract.py` → 54 passed, 2 skipped (56 coletados).

## Review Focus

1. **Loops do pacote com tamanho/fps/quadros diferentes** → erro claro nomeando o arquivo divergente, nunca uma mistura torta. Teste em Task 2.
2. **Arquivo do pacote faltando** → erro que nomeia o caminho que falta, antes de decodificar qualquer coisa. Teste em Task 2.
3. **Música mais longa que o loop** (sempre é) → o quadro do loop dá a volta (`i mod n`) e a saída tem a duração do áudio. Teste em Task 2.
4. **Instrumental de volume constante ou vazio** → tudo em CALMO, sem divisão por zero. Teste em Task 1.
5. **Falha no meio da composição** → nenhum `background_scene.mp4` parcial fica no disco (o 09 o usaria). Teste em Task 2.

---

### Task 1: Partitura — `karaoke/scene_score.py`

**Files:**
- Create: `karaoke/scene_score.py`
- Test: `tests/test_scene_score.py`

**Interfaces:**
- Consumes: nada de outras tarefas.
- Produces:
  - `CALMO, TENSAO, CLIMAX, ESCURO = 0, 1, 2, 3`
  - `envelope(rms: np.ndarray, frame_dur: float, fps: float, duracao: float) -> np.ndarray` (float, shape `(N,)`, `N = round(duracao*fps)`)
  - `estados(e: np.ndarray, fps: float) -> np.ndarray` (int, shape `(N,)`)
  - `pesos(est: np.ndarray, e: np.ndarray, fps: float) -> np.ndarray` (float, shape `(N, 4)`)
  - `ganho_fogo(onsets, fps: float, n: int) -> np.ndarray` (float, shape `(n,)`)
  - `score(rms, frame_dur, onsets, fps, duracao) -> tuple[est, w, g]`

- [ ] **Step 1: Escrever os testes que falham**

`tests/test_scene_score.py`:

```python
"""Partitura da cena reativa. Envelopes sinteticos, sem audio.

Os minimos esperados sao LITERAIS da spec, nao lidos do modulo: sabotar a
constante no modulo tem de deixar o teste vermelho.
"""
import numpy as np

from karaoke import scene_score as ss

FPS = 25


def _runs(est):
    """[(estado, n_quadros)] na ordem."""
    out = []
    for s in est:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([int(s), 1])
    return [tuple(r) for r in out]


def _serie(*trechos):
    """trechos: (valor_inicial, valor_final, segundos) -> e por quadro."""
    return np.concatenate([np.linspace(a, b, int(round(s * FPS)), endpoint=False)
                           for a, b, s in trechos])


def test_silencio_fica_todo_em_calmo():
    est, w, g = ss.score(np.zeros(3000), 0.01, [], FPS, 30.0)
    assert len(est) == 750, "cardinalidade: 30 s a 25 fps"
    assert (est == ss.CALMO).sum() == 750
    assert np.allclose(w[:, 0], 1.0)
    assert np.allclose(g, 1.0)


def test_volume_constante_nao_divide_por_zero():
    e = ss.envelope(np.full(3000, 0.3), 0.01, FPS, 30.0)
    assert len(e) == 750
    assert np.all(e == 0.0)


def test_subida_plato_queda_segue_a_ordem():
    e = _serie((0, 0, 5), (0, 1, 3), (1, 1, 8), (0, 0, 10))
    ordem = [s for s, _ in _runs(ss.estados(e, FPS))]
    assert ordem == [ss.CALMO, ss.TENSAO, ss.CLIMAX, ss.ESCURO, ss.CALMO]


def test_alto_constante_respeita_teto_e_cicla():
    est = ss.estados(np.ones(60 * FPS), FPS)
    runs = _runs(est)
    climax = [n for s, n in runs if s == ss.CLIMAX]
    assert len(climax) >= 1, "cardinalidade: tem de haver clímax"
    assert max(climax) <= 20 * FPS, f"clímax passou do teto: {max(climax)} quadros"
    ordem = [s for s, _ in runs]
    ciclo = [ss.CALMO, ss.TENSAO, ss.CLIMAX, ss.ESCURO, ss.CALMO]
    assert any(ordem[i:i + 5] == ciclo for i in range(len(ordem))), ordem


SEED = 0  # ver Step 2: escolhida pela regra de cardinalidade


def _passeio():
    rng = np.random.default_rng(SEED)
    return np.clip(0.5 + np.cumsum(rng.normal(0, 0.03, 300 * FPS)), 0, 1)


def test_nenhum_estado_abaixo_do_minimo():
    runs = _runs(ss.estados(_passeio(), FPS))
    completos = runs[1:-1]            # primeiro e ultimo podem estar cortados
    minimo = {ss.CALMO: 4.0, ss.TENSAO: 3.0, ss.CLIMAX: 3.0, ss.ESCURO: 2.5}
    vistos = {s: sum(1 for r, _ in completos if r == s) for s in minimo}
    assert all(n >= 2 for n in vistos.values()), f"cardinalidade: {vistos}"
    curtos = [(s, n) for s, n in completos if n < round(minimo[s] * FPS)]
    assert not curtos, f"{len(curtos)} de {len(completos)} runs abaixo do mínimo: {curtos[:5]}"


def test_pesos_somam_um_em_todo_quadro():
    e = _passeio()
    w = ss.pesos(ss.estados(e, FPS), e, FPS)
    assert w.shape == (len(e), 4) and len(e) > 0
    assert np.allclose(w.sum(axis=1), 1.0), f"{(~np.isclose(w.sum(1), 1)).sum()} de {len(e)} quadros"
    assert (w >= -1e-9).all()


def test_tensao_revela_mais_com_mais_energia():
    est = np.full(10 * FPS, ss.TENSAO)
    baixo = ss.pesos(est, np.full(10 * FPS, 0.0), FPS)[-1]
    alto = ss.pesos(est, np.full(10 * FPS, 1.0), FPS)[-1]
    assert np.allclose(baixo, [0.6, 0.4, 0, 0], atol=1e-6)
    assert np.allclose(alto, [0.0, 1.0, 0, 0], atol=1e-6)


def test_troca_nao_e_corte_seco():
    est = np.array([ss.CALMO] * FPS + [ss.CLIMAX] * (3 * FPS))
    w = ss.pesos(est, np.zeros(len(est)), FPS)
    assert 0.0 < w[FPS + 5, 2] < 1.0, "rampa de 1,2 s: no meio ainda mistura"
    assert np.isclose(w[FPS + int(1.2 * FPS) + 1, 2], 1.0)


def test_ganho_fogo_pulsa_e_decai():
    g = ss.ganho_fogo([1.0], FPS, 3 * FPS)
    assert np.isclose(g[FPS], 1.25)
    assert np.isclose(g[FPS - 1], 1.0)
    assert 1.0 < g[FPS + 8] < 1.125               # 0,32 s depois: 1 + 0,25·e^(-0,32/0,3) ≈ 1,086
    assert g[-1] < 1.01
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_scene_score.py -q`
Expected: erro de coleta `ModuleNotFoundError: No module named 'karaoke.scene_score'`.

- [ ] **Step 3: Implementar**

`karaoke/scene_score.py`:

```python
"""
Partitura da cena reativa: energia do instrumental -> estado, pesos dos 4
loops e ganho da fogueira, quadro a quadro. Logica pura, sem I/O.

Spec: docs/superpowers/specs/2026-09-30-cena-reativa-design.md
"""
from __future__ import annotations

import numpy as np

CALMO, TENSAO, CLIMAX, ESCURO = 0, 1, 2, 3

SUAVIZA_S = 1.5
LIMIAR_TENSAO, SUST_TENSAO_S, MIN_CALMO_S = 0.45, 1.0, 4.0
LIMIAR_CLIMAX, SUST_CLIMAX_S, MIN_TENSAO_S = 0.75, 2.0, 4.0
LIMIAR_DISSIPA, SUST_DISSIPA_S = 0.30, 3.0
LIMIAR_QUEDA, MIN_CLIMAX_S, TETO_CLIMAX_S = 0.55, 3.0, 20.0
DUR_ESCURO_S = 2.5

RAMPA_S, RAMPA_ESCURO_S, RAMPA_CALMO_S = 1.2, 0.6, 2.0
TENSAO_BASE, TENSAO_GANHO = 0.4, 0.6

FOGO_PULSO, FOGO_DECAI_S = 0.25, 0.3


def envelope(rms, frame_dur, fps, duracao):
    n = int(round(duracao * fps))
    rms = np.asarray(rms, dtype=np.float64)
    if n <= 0 or len(rms) == 0:
        return np.zeros(max(n, 0))
    janela = max(1, int(round(SUAVIZA_S / frame_dur)))
    liso = np.convolve(rms, np.ones(janela) / janela, mode="same")
    p10, p90 = np.percentile(liso, [10, 90])
    if p90 - p10 < 1e-6:
        return np.zeros(n)
    idx = np.minimum((np.arange(n) / fps / frame_dur).astype(int), len(liso) - 1)
    return np.clip((liso[idx] - p10) / (p90 - p10), 0.0, 1.0)


def estados(e, fps):
    q = lambda s: int(round(s * fps))  # noqa: E731 — segundos -> quadros
    out = np.empty(len(e), dtype=int)
    s, t_est, t_alto, t_baixo = CALMO, 0, 0, 0
    for i, x in enumerate(e):
        out[i] = s
        t_est += 1
        prox = s
        if s == CALMO:
            t_alto = t_alto + 1 if x > LIMIAR_TENSAO else 0
            if t_alto >= q(SUST_TENSAO_S) and t_est >= q(MIN_CALMO_S):
                prox = TENSAO
        elif s == TENSAO:
            t_alto = t_alto + 1 if x > LIMIAR_CLIMAX else 0
            t_baixo = t_baixo + 1 if x < LIMIAR_DISSIPA else 0
            if t_alto >= q(SUST_CLIMAX_S) and t_est >= q(MIN_TENSAO_S):
                prox = CLIMAX
            elif t_baixo >= q(SUST_DISSIPA_S):
                prox = CALMO
        elif s == CLIMAX:
            if t_est >= q(MIN_CLIMAX_S) and (x < LIMIAR_QUEDA or t_est >= q(TETO_CLIMAX_S)):
                prox = ESCURO
        elif t_est >= q(DUR_ESCURO_S):
            prox = CALMO
        if prox != s:
            s, t_est, t_alto, t_baixo = prox, 0, 0, 0
    return out


def pesos(est, e, fps):
    """Persegue o alvo do estado com rampa linear. Interpolacao convexa entre
    vetores que somam 1 continua somando 1 — por isso nao se limita componente
    a componente."""
    w = np.zeros((len(est), 4))
    atual = np.eye(4)[CALMO]
    for i, s in enumerate(est):
        if s == TENSAO:
            r = TENSAO_BASE + TENSAO_GANHO * float(e[i])
            alvo = np.array([1 - r, r, 0.0, 0.0])
        else:
            alvo = np.eye(4)[s]
        rampa = RAMPA_ESCURO_S if s == ESCURO else RAMPA_CALMO_S if s == CALMO else RAMPA_S
        dist = float(np.abs(alvo - atual).max())
        passo = 1.0 / (rampa * fps)
        atual = alvo.copy() if dist <= passo else atual + (passo / dist) * (alvo - atual)
        w[i] = atual
    return w


def ganho_fogo(onsets, fps, n):
    pulso = np.zeros(n)
    for t in onsets:
        k = int(t * fps)
        if 0 <= k < n:
            pulso[k] = 1.0
    decai = float(np.exp(-1.0 / (FOGO_DECAI_S * fps)))
    v, out = 0.0, np.empty(n)
    for i in range(n):
        v = max(pulso[i], v * decai)
        out[i] = 1.0 + FOGO_PULSO * v
    return out


def score(rms, frame_dur, onsets, fps, duracao):
    e = envelope(rms, frame_dur, fps, duracao)
    est = estados(e, fps)
    return est, pesos(est, e, fps), ganho_fogo(onsets, fps, len(e))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_scene_score.py -q`
Expected: 9 passed.

Bifurcação explícita: se **só** `test_nenhum_estado_abaixo_do_minimo` falhar e a mensagem começar por `cardinalidade:`, o passeio da seed 0 não visitou todo estado duas vezes. Troque `SEED` por 1, 2, … 9, nesta ordem, e fique com a primeira que passa; anote no comentário da linha `SEED = n  # seeds 0..n-1 reprovadas na cardinalidade`. Se nenhuma de 0..9 passar, **pare** e reporte os `vistos` de cada seed. Qualquer outra falha: `superpowers:systematic-debugging`, não mexa na seed.

- [ ] **Step 5: Controle negativo (faz parte do teste)**

a) Em `estados`, troque `or t_est >= q(TETO_CLIMAX_S)` por `or False`. Rode `python -m pytest tests/test_scene_score.py -q -k teto`. Esperado: **FAIL**. Desfaça.

b) Em `estados`, troque `and t_est >= q(MIN_CALMO_S)` por nada (condição só `t_alto >= q(SUST_TENSAO_S)`) **e** `t_est >= q(MIN_CLIMAX_S) and ` por nada. Rode `-k minimo`. Esperado: **FAIL** na linha `curtos`. Desfaça.

c) Rode o arquivo inteiro de novo: 9 passed. `git diff karaoke/scene_score.py` deve mostrar só o arquivo novo, sem as sabotagens.

Se a) ou b) ficar verde, o teste não cerca nada: **pare** e reporte.

- [ ] **Step 6: Commit**

```bash
git add karaoke/scene_score.py tests/test_scene_score.py
git commit -m "feat(cena): partitura — energia do instrumental vira estado, pesos e fogueira"
```

---

### Task 2: Compositor — `karaoke/scene_compose.py`

**Files:**
- Create: `karaoke/scene_compose.py`
- Modify: `karaoke/bounce.py` (extrair `read_mono_wav` de `onsets_from_wav`, linhas 106-124)
- Modify: `karaoke/paths.py` (depois de `background_png`, linha ~170)
- Test: `tests/test_scene_compose.py`

**Interfaces:**
- Consumes: nada da Task 1 (recebe arrays prontos).
- Produces:
  - `karaoke.bounce.read_mono_wav(wav_path: Path) -> tuple[np.ndarray, int]` — float32 mono normalizado em [-1, 1], sample rate.
  - `karaoke.paths.background_scene_mp4(job_id: str) -> Path` = `step_output(job_id, "08_background") / "background_scene.mp4"`
  - `ARQUIVOS_LOOP = ("calmo.mp4", "tensao.mp4", "climax.mp4", "escuro.mp4")`
  - `FAIXA_TOPO = (0.05, 0.25)`
  - `carregar_pacote(pasta: Path) -> tuple[list[np.ndarray], np.ndarray, float, dict]` — 4 loops `(n,h,w,3) uint8`, máscara `(h,w) float32` 0..1, fps, `scene.json` como dict (`{}` se ausente).
  - `misturar(quadros: np.ndarray (4,h,w,3) uint8, w: np.ndarray (4,), ganho: float, mascara: np.ndarray (h,w)) -> np.ndarray (h,w,3) uint8`
  - `compor(loops, mascara, w_todos: (N,4), g_todos: (N,), fps: float, saida: Path) -> list[float]` — luma média da faixa do topo por quadro; escreve `saida` atomicamente.
  - `fundo_do_job(scene_mp4: Path, bg_png: Path) -> tuple[Path | None, bool]` — (fundo, legenda_topo).

- [ ] **Step 1: Extrair `read_mono_wav` em `karaoke/bounce.py` (refatoração sem mudança de comportamento)**

Substitua o começo de `onsets_from_wav` (de `with wave.open` até `audio /= np.abs(audio).max() + 1e-8`) por uma chamada, e mova esse bloco para a função nova, mantendo o comentário do downmix:

```python
def read_mono_wav(wav_path: Path):
    """WAV int16 -> (float32 mono normalizado em [-1, 1], sample rate)."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        canais = wf.getnchannels()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = audio.astype(np.float32)
    if canais > 1:
        # (comentario original do downmix, sem mudanca)
        sobra = len(audio) % canais
        if sobra:
            audio = audio[:-sobra]     # frame parcial no fim do buffer
        audio = audio.reshape(-1, canais).mean(axis=1)
    audio /= np.abs(audio).max() + 1e-8
    return audio, sr


def onsets_from_wav(wav_path: Path) -> list:
    """RMS frame a frame + derivada, igual ao 05c_onset_dtw_align.py."""
    audio, sr = read_mono_wav(wav_path)
    hop = int(sr * HOP_MS / 1000)
    ...  # resto igual
```

Copie o comentário original do downmix literalmente para dentro de `read_mono_wav`.

Run: `python -m pytest tests/test_bounce.py -q`
Expected: mesmo resultado da linha de base (todos os de bounce passam).

- [ ] **Step 2: `background_scene_mp4` em `karaoke/paths.py`**

Logo após `background_png`:

```python
def background_scene_mp4(job_id: str) -> Path:
    """Fundo da cena reativa (Step 08c). Sidecar .json ao lado diz a legenda."""
    return step_output(job_id, "08_background") / "background_scene.mp4"
```

Run: `python -m pytest tests/test_paths_contract.py -q` → passa como na linha de base.

- [ ] **Step 3: Escrever os testes que falham**

`tests/test_scene_compose.py`:

```python
"""Compositor da cena. Loops sinteticos de cor chapada via ffmpeg lavfi."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from karaoke import scene_compose as sc

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")

W, H, FPS, LOOP_S = 64, 36, 8, 3
CORES = {"calmo.mp4": "red", "tensao.mp4": "lime", "climax.mp4": "blue", "escuro.mp4": "black"}


def _loop(p: Path, cor: str, w=W, h=H, fps=FPS, dur=LOOP_S):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c={cor}:s={w}x{h}:r={fps}:d={dur}",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(p)], check=True)


def _pacote(pasta: Path, **troca):
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, cor in CORES.items():
        _loop(pasta / nome, cor, **troca.get(nome, {}))
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"color=c=black:s={W}x{H}:d=1", "-frames:v", "1",
                    str(pasta / "fogo_mask.png")], check=True)
    (pasta / "scene.json").write_text(json.dumps({"legenda": "topo"}), encoding="utf-8")
    return pasta


def _quadros(mp4: Path):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, H, W, 3)


def test_misturar_e_convexa_e_aplica_ganho_so_na_mascara():
    q = np.zeros((4, 2, 2, 3), np.uint8)
    q[0] = 200
    q[3] = 0
    masc = np.array([[1, 0], [0, 0]], np.float32)
    out = sc.misturar(q, np.array([0.5, 0, 0, 0.5]), 1.25, masc)
    assert out[1, 1, 0] == 100
    assert out[0, 0, 0] == 125
    sat = sc.misturar(q, np.array([1.0, 0, 0, 0]), 1.5, masc)
    assert sat[0, 0, 0] == 255, "estouro satura, nao da a volta no uint8"


def test_pacote_carrega_na_ordem_certa(tmp_path):
    loops, masc, fps, meta = sc.carregar_pacote(_pacote(tmp_path / "c"))
    assert len(loops) == 4 and fps == FPS and meta == {"legenda": "topo"}
    assert masc.shape == (H, W)
    medias = [l[0].reshape(-1, 3).mean(0).round() for l in loops]
    assert medias[0][0] > 200 and medias[1][1] > 200 and medias[2][2] > 200
    assert medias[3].max() < 10


def test_arquivo_faltando_e_nomeado(tmp_path):
    pasta = _pacote(tmp_path / "c")
    (pasta / "climax.mp4").unlink()
    with pytest.raises(FileNotFoundError, match="climax.mp4"):
        sc.carregar_pacote(pasta)


def test_loop_divergente_e_nomeado(tmp_path):
    pasta = _pacote(tmp_path / "c", **{"tensao.mp4": {"w": 32}})
    with pytest.raises(ValueError, match="tensao.mp4"):
        sc.carregar_pacote(pasta)


def test_compor_da_a_volta_e_tem_a_duracao_da_musica(tmp_path):
    loops, masc, fps, _ = sc.carregar_pacote(_pacote(tmp_path / "c"))
    n = 5 * FPS                                   # 5 s > loop de 3 s
    w = np.zeros((n, 4))
    w[: n // 2, 0] = 1.0                          # calmo (vermelho)
    w[n // 2:, 3] = 1.0                           # escuro (preto)
    saida = tmp_path / "bg.mp4"
    faixa = sc.compor(loops, masc, w, np.ones(n), fps, saida)
    q = _quadros(saida)
    assert len(q) == n, f"{len(q)} quadros, esperado {n}"
    assert len(faixa) == n
    assert q[2].reshape(-1, 3).mean(0)[0] > 200, "inicio deveria ser o loop calmo"
    assert q[n - 2].max() < 16, "fim deveria ser o loop escuro"
    assert not list(tmp_path.glob("*.tmp*")), "sobrou temporario"


def test_falha_no_meio_nao_deixa_mp4(tmp_path):
    loops, masc, fps, _ = sc.carregar_pacote(_pacote(tmp_path / "c"))
    saida = tmp_path / "bg.mp4"
    with pytest.raises(Exception):
        # ganho mais curto que os pesos: IndexError no quadro 5, com o encoder ja aberto
        sc.compor(loops, masc, np.tile([1.0, 0, 0, 0], (10, 1)), np.ones(5), fps, saida)
    assert not saida.exists()
    assert not list(tmp_path.glob("*.tmp*"))


def test_fundo_do_job_prefere_cena_e_le_legenda(tmp_path):
    png = tmp_path / "background.png"
    png.write_bytes(b"x")
    cena = tmp_path / "background_scene.mp4"
    assert sc.fundo_do_job(cena, png) == (png, False)
    cena.write_bytes(b"x")
    cena.with_suffix(".json").write_text(json.dumps({"scene": "g", "legenda": "topo"}), encoding="utf-8")
    assert sc.fundo_do_job(cena, png) == (cena, True)
    png.unlink()
    cena.unlink()
    assert sc.fundo_do_job(cena, png) == (None, False)
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `python -m pytest tests/test_scene_compose.py -q`
Expected: erro de coleta `No module named 'karaoke.scene_compose'`.

- [ ] **Step 5: Implementar**

`karaoke/scene_compose.py`:

```python
"""
Compositor da cena reativa: 4 loops + mascara da fogueira + partitura ->
background_scene.mp4. Imagem e video entram e saem pelo ffmpeg (sem PIL).

Spec: docs/superpowers/specs/2026-09-30-cena-reativa-design.md
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

ARQUIVOS_LOOP = ("calmo.mp4", "tensao.mp4", "climax.mp4", "escuro.mp4")
FAIXA_TOPO = (0.05, 0.25)
# ponytail: os 4 loops inteiros em RAM (~100 MB cada a 832x480x81). Ler por
# pipe quadro a quadro se um pacote em 720p+ estourar a memoria.


def _sonda(mp4: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(num) / float(den)


def _decodifica(arq: Path, w: int, h: int, pix: str, extra=()) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(arq), *extra,
         "-f", "rawvideo", "-pix_fmt", pix, "-"],
        capture_output=True, check=True).stdout
    canais = 3 if pix == "rgb24" else 1
    return np.frombuffer(out, np.uint8).reshape(-1, h, w, canais)


def carregar_pacote(pasta: Path):
    pasta = Path(pasta)
    for nome in (*ARQUIVOS_LOOP, "fogo_mask.png"):
        if not (pasta / nome).exists():
            raise FileNotFoundError(f"pacote de cena incompleto: falta {pasta / nome}")
    ref = _sonda(pasta / ARQUIVOS_LOOP[0])
    w, h, fps = ref
    loops = []
    for nome in ARQUIVOS_LOOP:
        if _sonda(pasta / nome) != ref:
            raise ValueError(f"{nome}: {_sonda(pasta / nome)} difere de "
                             f"{ARQUIVOS_LOOP[0]}: {ref} (largura, altura, fps)")
        loops.append(_decodifica(pasta / nome, w, h, "rgb24"))
    contagens = [len(l) for l in loops]
    if len(set(contagens)) != 1:
        nome = ARQUIVOS_LOOP[contagens.index(min(contagens))]
        raise ValueError(f"{nome}: numero de quadros difere ({dict(zip(ARQUIVOS_LOOP, contagens))})")
    masc = _decodifica(pasta / "fogo_mask.png", w, h, "gray", ("-vf", f"scale={w}:{h}"))
    meta_p = pasta / "scene.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    return loops, masc[0, :, :, 0].astype(np.float32) / 255.0, fps, meta


def misturar(quadros, w, ganho, mascara):
    f = np.tensordot(np.asarray(w, np.float32), quadros.astype(np.float32), axes=1)
    f *= (1.0 + (ganho - 1.0) * mascara)[..., None]
    return np.clip(np.rint(f), 0, 255).astype(np.uint8)


def compor(loops, mascara, w_todos, g_todos, fps, saida: Path):
    w_todos = np.asarray(w_todos)
    if w_todos.ndim != 2 or w_todos.shape[1] != len(ARQUIVOS_LOOP):
        raise ValueError(f"pesos com forma {w_todos.shape}, esperado (N, 4)")
    n_loop, h, w, _ = loops[0].shape
    a, b = int(h * FAIXA_TOPO[0]), int(h * FAIXA_TOPO[1])
    saida = Path(saida)
    tmp = saida.with_name(saida.stem + ".tmp.mp4")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(tmp)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    faixa = []
    try:
        pilha = np.empty((4, h, w, 3), np.uint8)
        for i in range(len(w_todos)):
            for k in range(4):
                pilha[k] = loops[k][i % n_loop]
            q = misturar(pilha, w_todos[i], float(g_todos[i]), mascara)
            faixa.append(float(q[a:b].mean()))
            enc.stdin.write(q.tobytes())
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError(f"ffmpeg falhou: {enc.stderr.read().decode(errors='replace')[-1000:]}")
    except BaseException:
        if enc.poll() is None:
            enc.kill()
        enc.wait()
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, saida)
    return faixa


def fundo_do_job(scene_mp4: Path, bg_png: Path):
    scene_mp4, bg_png = Path(scene_mp4), Path(bg_png)
    if scene_mp4.exists():
        meta_p = scene_mp4.with_suffix(".json")
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        return scene_mp4, meta.get("legenda") == "topo"
    return (bg_png if bg_png.exists() else None), False
```

- [ ] **Step 6: Rodar e ver passar**

Run: `python -m pytest tests/test_scene_compose.py -q`
Expected: 7 passed.

- [ ] **Step 7: Controle negativo**

a) Em `carregar_pacote`, troque `for nome in ARQUIVOS_LOOP:` por `for nome in reversed(ARQUIVOS_LOOP):`. Rode `-k "ordem or volta"`. Esperado: **FAIL** nos dois. Desfaça.

b) Em `compor`, apague a linha `tmp.unlink(missing_ok=True)` do `except`. Rode `-k falha`. Esperado: **FAIL** (sobra `.tmp`). Desfaça.

c) Rode o arquivo inteiro: 7 passed. Se a) ou b) ficar verde, **pare** e reporte.

- [ ] **Step 8: Commit**

```bash
git add karaoke/scene_compose.py karaoke/bounce.py karaoke/paths.py tests/test_scene_compose.py
git commit -m "feat(cena): compositor — mistura os 4 loops por pipe do ffmpeg, escrita atomica"
```

---

### Task 3: Script do job — `scripts/08c_scene_background.py`

**Files:**
- Create: `scripts/08c_scene_background.py`

**Interfaces:**
- Consumes: `scene_score.score`, `scene_compose.carregar_pacote/compor`, `bounce.read_mono_wav`, `onset.compute_rms/detect_onsets`, `kpaths.demucs_out_dir/background_scene_mp4`.
- Produces: CLI `python scripts/08c_scene_background.py --job-id <id> --scene <nome>`; escreve `background_scene.mp4`, `background_scene.json` (`{"scene", "legenda"}`) e `background_scene_relatorio.json` (`{"fps", "estados": [[inicio_s, estado], ...], "faixa_topo_luma": [...]}`). Sai com código 1 e mensagem em qualquer falha.

- [ ] **Step 1: Implementar**

```python
"""
08c_scene_background.py — fundo da cena reativa para um job.

    python scripts/08c_scene_background.py --job-id <id> --scene guts_camp

Le input/scenes/<cena>/ e o no_vocals.wav do job; escreve, em
08_background/, background_scene.mp4 + .json (legenda) + _relatorio.json
(estados e brilho da faixa do topo por quadro, para o portao real).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths
from karaoke import onset, scene_compose, scene_score
from karaoke.bounce import read_mono_wav

RAIZ = Path(__file__).resolve().parent.parent
CENAS = RAIZ / "input" / "scenes"


def _duracao(wav: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
                         capture_output=True, text=True, check=True, timeout=30)
    return float(out.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--scene", required=True)
    args = ap.parse_args()

    print("=== Step 08c: Cena reativa ===")
    wav = kpaths.demucs_out_dir(args.job_id) / "no_vocals.wav"
    saida = kpaths.background_scene_mp4(args.job_id)
    try:
        if not wav.exists():
            raise FileNotFoundError(f"instrumental nao encontrado: {wav}")
        loops, masc, fps, meta = scene_compose.carregar_pacote(CENAS / args.scene)
        audio, sr = read_mono_wav(wav)
        rms, fd = onset.compute_rms(audio, sr)
        est, w, g = scene_score.score(rms, fd, onset.detect_onsets(rms, fd), fps, _duracao(wav))
        saida.parent.mkdir(parents=True, exist_ok=True)
        faixa = scene_compose.compor(loops, masc, w, g, fps, saida)
    except Exception as e:
        print(f"ERRO: cena '{args.scene}' nao gerada ({type(e).__name__}: {e})")
        sys.exit(1)

    legenda = meta.get("legenda", "baixo")
    saida.with_suffix(".json").write_text(
        json.dumps({"scene": args.scene, "legenda": legenda}), encoding="utf-8")
    trocas = [[round(i / fps, 2), int(s)] for i, s in enumerate(est) if i == 0 or s != est[i - 1]]
    saida.with_name("background_scene_relatorio.json").write_text(
        json.dumps({"fps": fps, "estados": trocas, "faixa_topo_luma": [round(x, 1) for x in faixa]}),
        encoding="utf-8")
    print(f"OK {saida.name}: {len(est)} quadros, {len(trocas)} trechos de estado, legenda={legenda}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificação de ponta (sem ComfyUI)**

Monte um job e um pacote sintéticos no scratchpad e rode o script de verdade. Em PowerShell ou Bash, com Python:

```python
# salvar como <scratchpad>/fumaca_08c.py e rodar com: python <scratchpad>/fumaca_08c.py
import json, shutil, subprocess, sys
from pathlib import Path
RAIZ = Path.cwd()
sys.path.insert(0, str(RAIZ))
import karaoke.paths as kpaths
job = "fumaca-cena"
cena = RAIZ / "input" / "scenes" / "_fumaca"
cena.mkdir(parents=True, exist_ok=True)
for nome, cor in {"calmo.mp4": "red", "tensao.mp4": "lime", "climax.mp4": "blue", "escuro.mp4": "black"}.items():
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s=64x36:r=8:d=3",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(cena / nome)], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=64x36:d=1",
                "-frames:v", "1", str(cena / "fogo_mask.png")], check=True)
(cena / "scene.json").write_text(json.dumps({"legenda": "topo"}), encoding="utf-8")
wav = kpaths.demucs_out_dir(job) / "no_vocals.wav"
wav.parent.mkdir(parents=True, exist_ok=True)
# 5 s silencio, 25 s ruido alto (energia sobe), 10 s silencio
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                "aevalsrc='if(between(t,5,30),0.8*(random(0)-0.5),0)':s=44100:d=40",
                "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
r = subprocess.run([sys.executable, "scripts/08c_scene_background.py", "--job-id", job, "--scene", "_fumaca"])
print("rc", r.returncode)
rel = json.loads((kpaths.background_scene_mp4(job).with_name("background_scene_relatorio.json")).read_text())
print("estados", rel["estados"], "quadros", len(rel["faixa_topo_luma"]))
```

Expected: `rc 0`; `quadros 320` (40 s × 8 fps); `estados` começa em `[0.0, 0]` e contém, em ordem, 1, 2, 3 e 0 de novo. Qualquer outra coisa: `superpowers:systematic-debugging`.

Depois apague o pacote e o job de fumaça: `input/scenes/_fumaca` e a pasta do job `fumaca-cena` (`kpaths.job_root("fumaca-cena")`). Confira antes de apagar que o caminho termina em `_fumaca`/`fumaca-cena`.

- [ ] **Step 3: Controle negativo**

Rode de novo com `--scene nao_existe`. Esperado: `rc 1` e mensagem com `falta` e o caminho de `calmo.mp4`.

- [ ] **Step 4: Commit**

```bash
git add scripts/08c_scene_background.py
git commit -m "feat(cena): step 08c gera background_scene.mp4 para um job"
```

---

### Task 4: Letra no topo e fundo da cena no render

**Files:**
- Modify: `karaoke/render_cmd.py:40-84` (`build_render_cmd`)
- Modify: `scripts/09_video_rendering.py:550-600`
- Test: `tests/test_render_cmd.py`

**Interfaces:**
- Consumes: `scene_compose.fundo_do_job`, `kpaths.background_scene_mp4`.
- Produces: `build_render_cmd(bg_png, audio_inputs, ass_path, out_mp4, duration, sendcmd_path, legenda_topo: bool = False)`.

- [ ] **Step 1: Testes que falham** — no fim de `tests/test_render_cmd.py`:

```python
def test_legenda_topo_forca_alinhamento_8():
    fc = _fc(build_render_cmd(BG, [INST, VOX], ASS, OUT, 210.0, SC, legenda_topo=True))
    assert ":force_style='Alignment=8'" in fc


def test_legenda_padrao_nao_forca_estilo():
    for bg in (BG, None):
        assert "force_style" not in _fc(build_render_cmd(bg, [INST, VOX], ASS, OUT, 210.0, None))
```

Run: `python -m pytest tests/test_render_cmd.py -q` → FAIL (`unexpected keyword argument 'legenda_topo'`).

- [ ] **Step 2: Implementar em `render_cmd.py`**

Assinatura ganha `legenda_topo: bool = False` (documente na docstring: "legenda_topo: True poe a letra no topo, Alignment=8 — cenas com detalhe embaixo"). Troque a linha do filtro:

```python
    sub = f"subtitles='{_escape(ass_path)}'"
    if legenda_topo:
        sub += ":force_style='Alignment=8'"
    filtros.append(sub)
```

Run: `python -m pytest tests/test_render_cmd.py -q` → todos passam.

- [ ] **Step 3: Verificação no binário real** (o filtergraph só vale medido via `subprocess.run` com lista, nunca no shell — ver docstring de `_escape`)

Salvar em `<scratchpad>/topo.py` e rodar com `python`:

```python
import subprocess, sys, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from karaoke.render_cmd import build_render_cmd
d = Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True)
ass = d / "t.ass"
ass.write_text(open("tests/fixtures/expected/en_ok.ass", encoding="utf-8").read(), encoding="utf-8")
for canal in ("a", "b"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", "6", str(d / f"{canal}.wav")], check=True)
for topo in (False, True):
    out = d / f"topo_{topo}.mp4"
    cmd = build_render_cmd(None, [d / "a.wav", d / "b.wav"], ass, out, 6.0, None, legenda_topo=topo)
    r = subprocess.run(cmd, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-800:]
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    q = np.frombuffer(raw, np.uint8).reshape(-1, 720, 1280).max(axis=0)
    print(topo, "topo(0.05-0.25):", int(q[36:180].max()), "baixo(0.62-0.92):", int(q[446:662].max()))
```

Run: `python <scratchpad>/topo.py <scratchpad>/topo`
Expected: linha `False` com baixo > 200 e topo < 30; linha `True` com topo > 200 e baixo < 30. Se `en_ok.ass` não tiver texto nos primeiros 6 s (os dois valores < 30 nas duas linhas), a cerca está vazia: aumente o `-t` e o `6.0` para a duração do último evento da fixture e rode de novo.

- [ ] **Step 4: Integrar em `scripts/09_video_rendering.py`**

Troque as duas linhas

```python
    bg_png = kpaths.background_png(job_id)
    bg_png = bg_png if bg_png.exists() else None
```

por

```python
    from karaoke.scene_compose import fundo_do_job
    bg_png, legenda_topo = fundo_do_job(kpaths.background_scene_mp4(job_id),
                                        kpaths.background_png(job_id))
```

e passe `legenda_topo=legenda_topo` nas **duas** chamadas de `build_render_cmd` (a normal e a `cmd_flat` do fallback — a letra não pode pular de lugar só porque o fundo falhou). Troque o print do fundo por:

```python
    rotulo = ("cena" if bg_png and bg_png.suffix == ".mp4"
              else "ilustracao" if bg_png else "chapado #08090f")
    print(f"  Fundo: {rotulo}{' (letra no topo)' if legenda_topo else ''}")
```

Run: `python -c "import ast,sys;ast.parse(open('scripts/09_video_rendering.py',encoding='utf-8').read())"` → sem saída.
Run: `python -m pytest tests/test_render_cmd.py tests/test_scene_compose.py -q` → todos passam.

- [ ] **Step 5: Controle negativo**

Troque `":force_style='Alignment=8'"` por `":force_style='Alignment=2'"` em `render_cmd.py`; rode `tests/test_render_cmd.py -k topo` → **FAIL**; rode `topo.py` → linha `True` volta a ter topo < 30. Desfaça.

- [ ] **Step 6: Commit**

```bash
git add karaoke/render_cmd.py scripts/09_video_rendering.py tests/test_render_cmd.py
git commit -m "feat(render): fundo da cena reativa e letra no topo quando a cena pede"
```

---

### Task 5: `--scene` no pipeline e faixa do topo na bancada

**Files:**
- Modify: `run_pipeline.py` (`build_steps`, linha 53; `main`, argparse ~linha 151 e chamada ~linha 200)
- Modify: `scripts/teste_loop_fundo.py` (`FAIXA_LEGENDA` linha 62, `medir` linha 111, argparse em `main`)
- Test: `tests/test_run_pipeline_scene.py`, `tests/test_teste_loop_fundo.py`

**Interfaces:**
- Produces: `build_steps(job_id, lang, romanization, aligner="mfa", scene=None)`; `medir(frames, faixa=FAIXA_LEGENDA)`; `FAIXA_TOPO = (0.05, 0.25)` em `teste_loop_fundo.py`; flag `--faixa {baixo,topo}`.

- [ ] **Step 1: Testes que falham**

`tests/test_run_pipeline_scene.py`:

```python
import run_pipeline as rp


def _nomes(steps):
    return [s["name"] for s in steps]


def test_sem_cena_lista_nao_muda():
    assert "Scene Background" not in _nomes(rp.build_steps("j", "pt", "none"))
    assert len(rp.build_steps("j", "pt", "none")) == 14


def test_com_cena_roda_08c_entre_ilustracao_e_render():
    steps = rp.build_steps("j", "pt", "none", scene="guts_camp")
    n = _nomes(steps)
    i = n.index("Scene Background")
    assert n[i - 1] == "Background Illustration" and n[i + 1] == "Video Rendering"
    cmd = steps[i]["cmd"]
    assert cmd[1].endswith("08c_scene_background.py")
    assert cmd[-2:] == ["--scene", "guts_camp"]
```

No fim de `tests/test_teste_loop_fundo.py`:

```python
def test_medir_aceita_faixa_do_topo():
    import numpy as np
    q = np.zeros((4, 100, 10, 3))
    q[:, 5:25] = 200.0                      # so o topo acende
    assert tlf.medir(q, tlf.FAIXA_TOPO)["faixa_legenda_luma_max"] == 200.0
    assert tlf.medir(q)["faixa_legenda_luma_max"] == 0.0
```

Run: `python -m pytest tests/test_run_pipeline_scene.py tests/test_teste_loop_fundo.py -q` → FAIL.

- [ ] **Step 2: Implementar**

`run_pipeline.py` — assinatura `def build_steps(job_id, lang, romanization, aligner="mfa", scene=None):` e, logo antes de `return steps`:

```python
    if scene:
        # So quando pedida: sem --scene os indices de --start-at nao mudam.
        i = [s["name"] for s in steps].index("Video Rendering")
        steps.insert(i, {
            "id": "11b", "name": "Scene Background",
            "cmd": [python, _p("scripts", "08c_scene_background.py"),
                    "--job-id", job_id, "--scene", scene],
        })
```

Argparse: `parser.add_argument("--scene", help="Cena reativa em input/scenes/<nome> (opcional)")`. Chamada: `build_steps(job_id, lang, romanization, args.aligner, args.scene)`.

`teste_loop_fundo.py` — abaixo de `FAIXA_LEGENDA`:

```python
FAIXA_TOPO = (0.05, 0.25)      # letra com Alignment=8 (cena reativa)
```

`def medir(frames, faixa=FAIXA_LEGENDA) -> dict:` e troque `FAIXA_LEGENDA[0]`/`[1]` dentro dela por `faixa[0]`/`faixa[1]`. No argparse de `main`: `ap.add_argument("--faixa", choices=["baixo", "topo"], default="baixo")` (use o nome real do parser em `main`) e na chamada `medir(fr, FAIXA_TOPO if args.faixa == "topo" else FAIXA_LEGENDA)`.

- [ ] **Step 3: Rodar**

Run: `python -m pytest tests/test_run_pipeline_scene.py tests/test_teste_loop_fundo.py tests/test_render_cmd.py tests/test_bounce.py tests/test_paths_contract.py tests/test_scene_score.py tests/test_scene_compose.py -q`
Expected: todos passam; total = 56 da linha de base + 2 (render_cmd) + 1 (loop_fundo) + 2 (pipeline) + 9 (score) + 7 (compose) = **77 coletados**, 2 skipped. Número diferente: reconcilie antes de seguir.

- [ ] **Step 4: Controle negativo**

Em `medir`, volte temporariamente a usar `FAIXA_LEGENDA` fixo; `-k topo` → **FAIL**. Desfaça. Em `build_steps`, troque `steps.insert(i, …)` por `steps.append(…)`; `-k entre` → **FAIL**. Desfaça.

- [ ] **Step 5: Commit**

```bash
git add run_pipeline.py scripts/teste_loop_fundo.py tests/test_run_pipeline_scene.py tests/test_teste_loop_fundo.py
git commit -m "feat(cena): --scene no pipeline e faixa do topo na bancada de loop"
```

---

### Task 6: Portão real — pacote `guts_camp` e uma música (manual, com o usuário)

Não é para subagente: depende do ComfyUI, da LoRA do usuário e do olho dele. Quem executa é a sessão principal, junto do usuário.

- [ ] **Step 1:** Usuário gera a mestre com a LoRA e o prompt da spec (frase de composição nova) e as 3 edições no Qwen-Image-Edit.
- [ ] **Step 2:** Para cada uma das 4 imagens: `python scripts/teste_loop_fundo.py --image <png> --faixa topo`. Registrar, das 4: `fecha`, `faixa_legenda_luma_max`, `faixa_legenda_respiracao` (4 de 4 reportados). Copiar os `loop.mp4` para `input/scenes/guts_camp/{calmo,tensao,climax,escuro}.mp4`; pintar `fogo_mask.png`; `scene.json` = `{"legenda": "topo"}`.
- [ ] **Step 3:** Rodar numa música real com instrumental já separado: `python scripts/08c_scene_background.py --job-id <id> --scene guts_camp` e depois `python scripts/09_video_rendering.py --job-id <id>`.
- [ ] **Step 4:** Do `background_scene_relatorio.json`: listar os trechos de estado com tempo e conferir ouvindo se o CLÍMAX cai nos trechos fortes; informar "X de N quadros com `faixa_topo_luma` acima de Y", com Y calibrado aqui e registrado na spec (seção Verificação).
- [ ] **Step 5:** Tira de contato do MP4 final; o usuário decide.
