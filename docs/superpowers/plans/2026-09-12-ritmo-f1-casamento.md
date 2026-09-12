# Ritmo por casamento de conjunto (F1 com alinhamento global) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A nota de ritmo de `score()` deixa de ser posicional (`_mad_intervalos`) e passa a ser `100 × F1` do casamento 1:1 entre ataques da referência e do take, depois de estimar o deslocamento global por correlação cruzada.

**Architecture:** Duas funções puras novas em `karaoke/scorer.py` (`_align_offset`, `_match_f1`), um bloco de `score()` trocado, três constantes viram duas, uma função e seus dois knobs somem. `ScoreReport` ganha `n_matched` (numerador do F1, para auditoria); a rota devolve esse campo (uma linha). Página intocada.

**Tech Stack:** Python 3.11 (`karaoke_env`), numpy 1.26.4, pytest 9.0.2.

Spec: [`docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md`](../specs/2026-09-10-scorer-mimic-karaoke-design.md), seção **"Emenda 2026-09-12 (2)"**. Ler antes de começar.

## Global Constraints

- **Zero dependência nova.** Se parecer exigir `pip install`, pare e reporte.
- **Interpretador**: `C:\Users\Katz\miniforge3\envs\karaoke_env\python.exe`. Testes com `python -m pytest` da raiz do worktree, **em primeiro plano**.
- **Nada de I/O em `karaoke/`.**
- **Só o que está escrito aqui.** Não toque em `track_from_audio`, `track_from_word_timing` (exceto o comentário `ponytail:` indicado), `karaoke/onset.py`, `web/mimic.html`. A rota (`server_score_addendum.py`) muda **uma linha** (Step 7). Se um passo parecer exigir mais, pare e reporte.
- **Controle negativo não é etapa opcional.** Cada cerca nova é vista vermelha antes de verde.
- **Denominador junto do número.** Mensagens de asserção dizem "X de Y".
- **Nenhum `.skip`, nenhum `sed -i`, nenhum `git stash`.**
- **Suíte em primeiro plano**, uma vez antes do commit.

### Valores de referência (protótipo `.08/bin`, 2026-09-12 — alegações até o Step 9 re-derivar)

| grandeza | valor |
|---|---|
| `MATCH_TOL_S` | 0,080 |
| `XCORR_BIN_S` | 0,010 |
| sintético: identidade / jitter ±40 ms / espúrio antes / nota extra / nota perdida | 100 / 100 / 90,9 / 90,9 / 88,9 |
| sintético: embaralhado / esticado 1,3× / clipe diferente | 40 / 40 / 50 |
| sintético: acaso n=30 seed 7 — ritmo p95 / total p95 | 64 / ≈64 |
| real `mimic_gab_01`: self / áudio inteiro / blocos 1 s embaralhados p95 (n=20) | 100 / 99,1 / 54 |
| real: take denso de ruído branco (251 ataques) | 46 — precisão 0,35 |

---

## File Structure

| arquivo | mudança |
|---|---|
| `karaoke/scorer.py` | knobs: `RHYTHM_TOL_RATIO`, `RHYTHM_TOL_FLOOR_S` **somem**; `MATCH_TOL_S`, `XCORR_BIN_S` **entram**. `_mad_intervalos` **some**. `_align_offset`, `_match_f1` **entram**. Bloco de ritmo de `score()` trocado. `ScoreReport.n_matched` entra. Docstring de `score()` e comentário `ponytail:` de `track_from_word_timing` atualizados. |
| `tests/test_scorer.py` | 2 testes retargetados (`test_ritmo_calibra_na_referencia_nao_no_take` → `test_ritmo_esticado_fica_abaixo_do_acaso`; `test_onset_espurio_antes...` piso 95 → 85); 3 testes novos (jitter, take denso, deslocamento global); import de `RHYTHM_TOL_FLOOR_S`/`RHYTHM_TOL_RATIO` se existir some. |
| `server_score_addendum.py` | `"n_matched": report.n_matched,` no `jsonify` (uma linha). |
| `tests/test_score_route.py` | só se algum teste comparar o conjunto exato de chaves da resposta (verificar com grep; hoje nenhum compara). |

---

### Task 1: ritmo = F1 do casamento com alinhamento global

**Files:**
- Modify: `karaoke/scorer.py:78-92` (knobs), `:95-104` (`ScoreReport`), `:113-130` (`_mad_intervalos` sai), `:133-172` (`score()`), `:191-195` (comentário `ponytail:`)
- Modify: `server_score_addendum.py:131-134` (uma linha)
- Test: `tests/test_scorer.py:166-195` (dois retargets) + fim do arquivo (três novos)

**Interfaces:**
- Consumes: `ReferenceTrack.onsets` (np.ndarray, segundos), `karaoke.audio_fixtures.bursts`, `SR`, `TIMES`, `FREQS`, `_baseline_aleatorio`, `_total`, `ref` fixture — todos já existem em `tests/test_scorer.py`.
- Produces:
  - `karaoke.scorer.MATCH_TOL_S: float = 0.080`, `karaoke.scorer.XCORR_BIN_S: float = 0.010`
  - `karaoke.scorer._align_offset(on_ref: np.ndarray, on_take: np.ndarray) -> float` — `b` em segundos tal que `take ≈ ref + b`.
  - `karaoke.scorer._match_f1(on_ref: np.ndarray, on_take_alinhado: np.ndarray) -> tuple[float, int]` — `(f1 em 0..1, n_pares)`.
  - `ScoreReport.n_matched: int` (novo campo, depois de `n_onsets_take`). `rhythm_tol_s` continua e vale `MATCH_TOL_S`.
  - `score()` mesma assinatura; `rhythm = 100 × f1`; `rhythm = 0.0` se `n_ref < 2` ou `n_take < 1`.

- [ ] **Step 1: Retargetar as duas cercas que pinavam o ritmo posicional**

Em `tests/test_scorer.py`, substitua `test_ritmo_calibra_na_referencia_nao_no_take` **inteira** (do `def` até o último `assert`) por:

```python
def test_ritmo_esticado_fica_abaixo_do_acaso(ref):
    """Take a 1.3x do andamento: a deriva estoura MATCH_TOL_S e o F1 cai ao nivel do
    acaso — sem termo de andamento (spec, emenda 2026-09-12 (2): medido 40 contra p95
    do acaso 64). Antes, com tolerancia relativa 0.21s, o conjunto casava quase tudo."""
    esticado = _total(ref, [t * 1.3 for t in TIMES], FREQS)
    assert esticado.n_onsets_take == len(TIMES), (
        f"{esticado.n_onsets_take} ataques de {len(TIMES)} no take esticado"
    )
    assert esticado.rhythm < 50.0, (
        f"take esticado 1.3x recebeu rhythm {esticado.rhythm:.1f} "
        f"({esticado.n_matched} de {esticado.n_onsets_ref} casados)"
    )
```

E em `test_onset_espurio_antes_nao_derruba_abaixo_do_acaso`, troque a linha do `rhythm`:

```python
    assert espurio.rhythm >= 85.0, (
        f"rhythm {espurio.rhythm:.1f} com um onset espurio antes "
        f"({espurio.n_matched} de {espurio.n_onsets_ref} casados, precisao 5/6 esperada)"
    )
```

(era `>= 95.0`; F1 com precisão 5/6 dá 90,9 — o espúrio custa, e é honesto que custe.)

Atualize também a docstring desse teste: substitua a frase "com tolerancia a um onset de borda da 80.9 (rhythm 100, attacks 83.3)" por "com casamento por conjunto da rhythm 90.9 (precisao 5 de 6) e total > p95 do acaso".

- [ ] **Step 2: Escrever as três cercas novas**

Acrescente ao **fim** de `tests/test_scorer.py`:

```python
def test_ritmo_jitter_humano_nao_custa(ref):
    """Cantar no tempo com +-40ms de jitter e o take BOM. Posicional dava 62;
    casamento com MATCH_TOL_S = 0.08 tem que dar ~100."""
    jitter = [0.04, -0.04, 0.04, -0.04, 0.04]
    r = _total(ref, [t + j for t, j in zip(TIMES, jitter)], FREQS)
    assert r.n_matched == len(TIMES), f"{r.n_matched} de {len(TIMES)} casados"
    assert r.rhythm >= 95.0, f"jitter de 40ms custou rhythm {r.rhythm:.1f}"


def test_ritmo_take_denso_paga_em_precisao(ref):
    """So recall e enganavel: um take com os 5 ataques certos MAIS 10 espurios casa
    100% da referencia. A precisao (5 de 15) e o que derruba. Controle: o recall
    sozinho seria 1.0 — visivel em n_matched == n_onsets_ref."""
    extras = [0.5, 0.7, 1.1, 1.3, 1.7, 2.0, 2.2, 2.6, 2.8, 3.2]
    times = sorted(TIMES + extras)
    freqs = FREQS + [300.0] * len(extras)
    denso = _total(ref, times, freqs)
    assert denso.n_onsets_take == 15, f"{denso.n_onsets_take} ataques de 15 no take denso"
    assert denso.n_matched == len(TIMES), (
        f"controle: recall deveria ser cheio, casou {denso.n_matched} de {len(TIMES)}"
    )
    assert denso.rhythm < 60.0, (
        f"take denso recebeu rhythm {denso.rhythm:.1f} com precisao "
        f"{denso.n_matched}/{denso.n_onsets_take}"
    )


def test_ritmo_deslocamento_global_e_estimado_nao_assumido(ref):
    """Pre-roll de 0.45s no take (latencia, respiracao) custa zero: o offset vem da
    correlacao cruzada. Controle negativo: sem alinhar (b=0) o casamento a 0.08s
    nao acha nada — 0.45 e escolhido para que o par nao alinhado mais proximo fique
    a 0.15s (0.9 vs 0.75), longe da tolerancia; 0.5 deixaria pares a 0.10s."""
    from karaoke.scorer import _align_offset, _match_f1, MATCH_TOL_S
    take = track_from_audio(bursts([t + 0.45 for t in TIMES], FREQS), SR)
    b = _align_offset(ref.onsets, take.onsets)
    assert abs(b - 0.45) <= MATCH_TOL_S, f"offset estimado {b:.3f}s, esperado 0.45s"
    f1_sem, n_sem = _match_f1(ref.onsets, take.onsets)
    assert n_sem == 0, f"controle: sem alinhar casou {n_sem} de {len(TIMES)}"
    r = score(ref, take)
    assert r.n_matched == len(TIMES), f"{r.n_matched} de {len(TIMES)} casados"
    assert r.rhythm >= 95.0, f"pre-roll de 0.45s custou rhythm {r.rhythm:.1f}"
```

- [ ] **Step 3: Rodar e ver vermelho**

Run: `python -m pytest tests/test_scorer.py -q -k "ritmo or espurio"`
Expected: FAIL — `AttributeError: 'ScoreReport' object has no attribute 'n_matched'` e/ou `ImportError` de `_align_offset`. Anote "X failed, Y passed".

- [ ] **Step 4: Implementar em `karaoke/scorer.py`**

(a) Substitua o bloco de knobs (linhas 78–85, do comentário `# ── Knobs de nota` até `WEIGHTS = {...}`) por:

```python
# ── Knobs de nota ────────────────────────────────────────────────────────────
# Ritmo = F1 do casamento 1:1 entre ataques da referencia e do take, depois de
# estimar o deslocamento global. Tolerancia FIXA: relativa ao intervalo mediano
# virava 0,21s no sintetico e o acaso subia a p95 75 (medido 2026-09-12); 0,05s
# dava 60 a um humano com jitter +-40ms, a 8 pontos do acaso. MIREX usa 50ms.
MATCH_TOL_S = 0.080
XCORR_BIN_S = 0.010        # grade do trem de impulsos para o alinhamento global
WEIGHTS = {"melody": 0.45, "rhythm": 0.35, "attacks": 0.20}
```

(b) Em `ScoreReport`, acrescente depois de `n_onsets_take: int`:

```python
    n_matched: int          # numerador do F1: pares casados dentro de rhythm_tol_s
```

e troque o comentário de `rhythm_tol_s` para `# = MATCH_TOL_S, para auditoria`.

(c) Substitua `_mad_intervalos` **inteira** (do `def` até `return best if ...`) por:

```python
def _align_offset(on_ref: np.ndarray, on_take: np.ndarray) -> float:
    """Deslocamento global b tal que take ~ ref + b: pico da correlacao cruzada
    entre trens de impulso triangulares (largura MATCH_TOL_S) em grade XCORR_BIN_S.
    E o que torna o ritmo imune a latencia de captura e pre-roll SEM assumir
    sincronia: o offset e medido, nao suposto."""
    w = max(1, int(round(MATCH_TOL_S / XCORR_BIN_S)))
    n = int(max(float(on_ref.max()), float(on_take.max())) / XCORR_BIN_S) + w + 2

    def trem(on: np.ndarray) -> np.ndarray:
        tr = np.zeros(n, dtype=np.float64)
        for t in on:
            c = int(round(float(t) / XCORR_BIN_S))
            lo, hi = max(0, c - w), min(n - 1, c + w)
            k = np.arange(lo, hi + 1)
            tr[k] = np.maximum(tr[k], 1.0 - np.abs(k - c) / (w + 1))
        return tr

    xc = np.correlate(trem(on_take), trem(on_ref), mode="full")
    return (int(np.argmax(xc)) - (n - 1)) * XCORR_BIN_S


def _match_f1(on_ref: np.ndarray, on_take_alinhado: np.ndarray) -> tuple[float, int]:
    """Casamento 1:1 guloso por proximidade dentro de MATCH_TOL_S. Devolve
    (F1, n_pares). Recall = pares/n_ref; precisao = pares/n_take — a precisao e
    o que derruba o take denso (ruido: 251 ataques, precisao 0,35, medido)."""
    n_ref, n_take = len(on_ref), len(on_take_alinhado)
    if n_ref == 0 or n_take == 0:
        return 0.0, 0
    usado = np.zeros(n_take, dtype=bool)
    pares = 0
    for t in on_ref:
        d = np.abs(on_take_alinhado - t)
        d[usado] = np.inf
        j = int(np.argmin(d))
        if d[j] <= MATCH_TOL_S:
            usado[j] = True
            pares += 1
    recall, precisao = pares / n_ref, pares / n_take
    f1 = 2 * recall * precisao / (recall + precisao) if pares else 0.0
    return f1, pares
```

(d) Em `score()`, substitua o bloco de ritmo (do comentário `# ritmo: intervalos ENTRE ataques` até `rhythm = 0.0`, linhas 141–149) por:

```python
    # ritmo: F1 do casamento de ataques apos alinhamento global (spec, emenda
    # 2026-09-12 (2)). Posicional dava 0.0 ao vocal inteiro, a sala e aos blocos
    # embaralhados — nao distinguia take bom de aleatorio.
    tol = MATCH_TOL_S
    if n_ref >= 2 and n_take >= 1:
        b = _align_offset(ref.onsets, take.onsets)
        f1, n_matched = _match_f1(ref.onsets, take.onsets - b)
        rhythm = 100.0 * f1
    else:
        rhythm, n_matched = 0.0, 0
```

e no `return ScoreReport(...)` acrescente `n_matched=n_matched,` logo depois de `n_onsets_take=n_take,`.

(e) Docstring de `score()`: substitua por

```python
    """Compara forma relativa, nunca sincronia absoluta: um atraso global na
    captura e ESTIMADO (correlacao cruzada) e descontado, nao assumido."""
```

(f) No comentário `ponytail:` de `track_from_word_timing` (linhas 191–195), substitua o parágrafo inteiro por:

```
    ponytail: teto documentado, NAO desta funcao — take com 1 clique de botao da
    rhythm 38 porque track_from_audio normaliza por pico de amostra (39 de 164
    ataques sobrevivem), e o take inteiro perde melodia (73,8) porque o pre-vocal
    contamina o pyin. Os dois sao "o take tem coisa que a referencia nao tem":
    VAD no inicio do take, decisao de spec seguinte.
```

(g) Confira que nada mais no módulo referencia `RHYTHM_TOL_RATIO`, `RHYTHM_TOL_FLOOR_S` ou `_mad_intervalos`: `grep -n "RHYTHM_TOL\|_mad_intervalos" karaoke/*.py tests/*.py server*.py scripts/*.py`. Expected: nenhuma ocorrência fora de docs. Se houver em `tests/test_scorer.py` (import), remova do import.

- [ ] **Step 5: Rodar e ver verde**

Run: `python -m pytest tests/test_scorer.py -q`
Expected: todos passam; contagem = a de antes + 3. Se `test_ritmo_take_denso_paga_em_precisao` falhar no **controle** (`n_matched < 5` — algum extra roubou um ataque certo no guloso), **pare e reporte com os números**; não mova os extras.

- [ ] **Step 6: Conferir as três relações inegociáveis com os números novos**

Run: `python -m pytest tests/test_scorer.py -q -k "controle or relacoes"`
Expected: verde. O p95 do acaso sobe (≈52,8 → ≈64); identidade continua 100 > p95; clipe diferente ≈29,5 < p95. Cole os números da mensagem de asserção de `test_relacoes_de_ordem_completas` se ela falhar.

- [ ] **Step 7: Rota devolve `n_matched`**

Em `server_score_addendum.py`, no `jsonify({...})` da rota `POST /api/score`, acrescente logo depois da linha `"n_onsets_take": report.n_onsets_take,`:

```python
            "n_matched": report.n_matched,
```

Confira: `grep -n "n_onsets_take\|keys()" tests/test_score_route.py`. Se algum teste comparar o conjunto exato de chaves, acrescente `n_matched` nele; se nenhum, nada a fazer.

- [ ] **Step 8: Suíte do scorer em primeiro plano**

Run: `python -m pytest tests/test_scorer.py tests/test_onset.py tests/test_score_route.py -q`
Expected: verde. Anote "X passed".

- [ ] **Step 9: Re-derivar no job real**

Da raiz do worktree:

```bash
python -X utf8 - <<'EOF'
import json, numpy as np, soundfile as sf
from pathlib import Path
from karaoke.scorer import score, track_from_audio, track_from_word_timing, WINDOW_PAD_S
job = Path(r"C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\.claude\worktrees\mimic-party-discord-logic-4b5f14\work\jobs\mimic_gab_01")
words = json.loads((job / "05_alignment" / "word_timing.json").read_text(encoding="utf-8"))
x, sr = sf.read(job / "03_vocals_clean" / "vocals_raw.wav", dtype="float32")
if x.ndim > 1: x = x.mean(axis=1)
ref = track_from_word_timing(words, x, sr)
def linha(nome, take):
    r = score(ref, take)
    print(f"{nome:<22} ref={r.n_onsets_ref} take={r.n_onsets_take} casados={r.n_matched} "
          f"melody={r.melody:.1f} rhythm={r.rhythm:.1f} attacks={r.attacks:.1f} total={r.total:.1f}")
t0 = max(0.0, words[0]["start"] - WINDOW_PAD_S); t1 = min(len(x)/sr, words[-1]["end"] + WINDOW_PAD_S)
win = x[int(t0*sr):int(t1*sr)]
linha("self (janela)", track_from_audio(win, sr))
linha("audio inteiro", track_from_audio(x, sr))
rng = np.random.default_rng(7)
bl = int(sr); blocos = [win[i:i+bl] for i in range(0, len(win)-bl, bl)]
rs = [score(ref, track_from_audio(np.concatenate([blocos[i] for i in rng.permutation(len(blocos))]), sr)).rhythm for _ in range(20)]
print(f"blocos embaralhados n=20 rhythm media={np.mean(rs):.1f} p95={np.percentile(rs,95):.1f}")
EOF
```

Expected: self rhythm 100; áudio inteiro rhythm ≥ 95 (protótipo: 99,1) e total ≥ 85 (protótipo: 87,8); blocos p95 ≤ 60 (protótipo: 54). Cole as quatro linhas no relatório. Se os arquivos não existirem, reporte o caminho — não invente número.

- [ ] **Step 10: Commit**

```bash
git add karaoke/scorer.py tests/test_scorer.py server_score_addendum.py
git commit -m "feat(scorer): ritmo por F1 do casamento de ataques com alinhamento global; _mad_intervalos sai

Posicional (diff indice a indice, tol relativa com clamp em zero) dava rhythm 0.0
ao vocal inteiro, a sala e aos blocos embaralhados — nao distinguia take bom de
aleatorio. Agora: deslocamento global por correlacao cruzada de trens de impulso,
casamento 1:1 dentro de MATCH_TOL_S = 0.08, rhythm = 100 x F1. Precisao e o que
derruba o take denso.

Medido no job mimic_gab_01: audio inteiro rhythm 0 -> <VALOR>, total 53.1 -> <VALOR>;
blocos de 1s embaralhados p95 <VALOR>. Sintetico: jitter +-40ms 62 -> 100, nota
extra 29 -> 91, esticado 1.3x 40 (nivel do acaso), acaso p95 52.8 -> ~64.
Some _mad_intervalos e o P1 parked (tolerancia a onset de borda): o conjunto
absorve isso de graca. ScoreReport ganha n_matched.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Substitua cada `<VALOR>` pelo número do Step 9 — **nunca** commite com placeholder nem com número que você não mediu.

---

## Notas de execução

- `web/mimic.html` mostra `rhythm_tol_s` na auditoria; passa a exibir 0.08 fixo. Consequência, não bug.
- O plano anterior (`2026-09-12-karaoke-ref-janela-audio.md`) e a memória citavam "P1: `_mad_intervalos` mascara erro no meio de frase" — deixa de existir com esta tarefa.
