# Modo karaoke: referência via `track_from_audio` no recorte do gabarito — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `track_from_word_timing` deixa de usar inícios de palavra como ataques e passa a extrair a referência do modo karaoke com `track_from_audio` sobre o recorte `[words[0].start − 0,1 s, words[-1].end + 0,1 s]` do vocal isolado, usando o gabarito só para validar e janelar.

**Architecture:** Uma função muda de corpo, ganha uma constante nomeada (`WINDOW_PAD_S`) e duas validações a mais. A rota Flask, `score()`, `ReferenceTrack` e a página não mudam. Um teste é retargetado, dois nascem. Nada de I/O em `karaoke/`.

**Tech Stack:** Python 3.11 (`karaoke_env`), numpy 1.26.4, librosa 0.11.0, pytest 9.0.2.

Spec: [`docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md`](../specs/2026-09-10-scorer-mimic-karaoke-design.md), seção **"Emenda 2026-09-12"**. Ler antes de começar.

## Global Constraints

Valem para toda tarefa. Os requisitos de cada tarefa incluem esta seção implicitamente.

- **Zero dependência nova.** Se parecer exigir `pip install`, pare e reporte.
- **Interpretador**: `C:\Users\Katz\miniforge3\envs\karaoke_env\python.exe`. Os testes rodam com `python -m pytest` a partir da raiz do worktree, **em primeiro plano** — nunca em background.
- **Nada de I/O em `karaoke/`.** `track_from_word_timing` continua recebendo `samples` já lidos; leitura de disco fica em `server_score_addendum.py`.
- **Só o que está escrito aqui.** Não toque em `score()`, `_mad_intervalos`, `track_from_audio`, `server_score_addendum.py`, `web/mimic.html` nem em `karaoke/onset.py`. Se um passo parecer exigir isso, pare e reporte — não decida.
- **Controle negativo não é etapa opcional.** Cada teste novo tem um passo em que é visto vermelho.
- **Denominador junto do número.** Mensagens de asserção dizem "X de Y".
- **Nenhuma migração, nenhum `.skip`, nenhum `sed -i`.**

### Valores de referência (spec, emenda 2026-09-12)

| grandeza | valor |
|---|---|
| `WINDOW_PAD_S` | 0,1 s |
| self-score no job real `mimic_gab_01` depois da mudança | ~~100,0~~ — **corrigido na execução**: 53,1 com take = vocal inteiro; 100,0 só janela contra a própria janela (ver Notas de execução) |
| take deslocado no job real depois da mudança | 62,1 — **teto do ritmo posicional, pré-existente; NÃO é critério de aceite** |
| fixture sintética `bursts(TIMES, FREQS)` | 5 ataques em `TIMES = [0.3, 0.9, 1.5, 2.4, 3.0]` |

---

## File Structure

| arquivo | mudança |
|---|---|
| `karaoke/scorer.py` | `WINDOW_PAD_S` (constante nova, topo do módulo junto dos knobs de calibração); corpo de `track_from_word_timing` reescrito; docstring e comentário `ponytail:` atualizados |
| `tests/test_scorer.py` | `test_karaoke_usa_inicios_de_palavra_como_ataques` **retargetado** para `test_karaoke_ataques_vem_do_audio_dentro_da_janela`; **novos** `test_karaoke_janela_exclui_ataque_fora_do_gabarito` e `test_karaoke_folga_captura_o_primeiro_ataque`; `test_karaoke_pontua_contra_si_mesmo` sobe o piso de 80 para 95; **novo** `test_karaoke_gabarito_sem_end_ou_janela_vazia_e_erro` |

---

### Task 1: `track_from_word_timing` recorta e delega a `track_from_audio`

**Files:**
- Modify: `karaoke/scorer.py:83-85` (knobs) e `karaoke/scorer.py:168-206` (função inteira)
- Test: `tests/test_scorer.py:207-254`

**Interfaces:**
- Consumes: `karaoke.scorer.track_from_audio(samples, sr) -> ReferenceTrack` (inalterada), `karaoke.audio_fixtures.bursts`, `SR`, `TIMES`, `FREQS` já importados no teste.
- Produces: `karaoke.scorer.track_from_word_timing(words: list[dict], samples: np.ndarray, sr: int) -> ReferenceTrack` — mesma assinatura, mesmo tipo de retorno. `onsets` **relativos ao início da janela**. Levanta `ValueError` em: `words` vazio; `start` não monotônico; último `word` sem chave `end`; janela vazia depois de recortar ao áudio. Constante nova `karaoke.scorer.WINDOW_PAD_S: float = 0.1`.

- [ ] **Step 1: Retargetar o teste que pinava "ataques = inícios de palavra"**

Em `tests/test_scorer.py`, substitua a função `test_karaoke_usa_inicios_de_palavra_como_ataques` inteira (da linha `def` até o último `assert`, imediatamente antes de `def test_karaoke_gabarito_vazio_e_erro_nao_nota_zero`) por:

```python
def test_karaoke_ataques_vem_do_audio_dentro_da_janela():
    """Os ataques vem do DETECTOR sobre o recorte do gabarito, nao dos inicios de
    palavra. Mesma populacao que o take: e o que faz attacks e rhythm compararem
    igual com igual (spec, emenda 2026-09-12)."""
    words = [
        {"word": "um", "start": 0.30, "end": 0.55, "score": 1.0},
        {"word": "dois", "start": 0.90, "end": 1.15, "score": 1.0},
        {"word": "tres", "start": 1.50, "end": 1.75, "score": 1.0},
        {"word": "quatro", "start": 2.40, "end": 2.65, "score": 1.0},
        {"word": "cinco", "start": 3.00, "end": 3.25, "score": 1.0},
    ]
    audio = bursts(TIMES, FREQS)
    track = track_from_word_timing(words, audio, SR)
    direto = track_from_audio(audio, SR)

    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} bursts na janela"
    )
    # mesmos intervalos que o detector acha no audio inteiro: a janela so desloca
    np.testing.assert_allclose(np.diff(track.onsets), np.diff(direto.onsets), atol=0.02)
    # onsets sao relativos ao inicio da janela: o primeiro cai a ~WINDOW_PAD_S
    assert abs(track.onsets[0] - WINDOW_PAD_S) <= 0.03, (
        f"primeiro ataque em {track.onsets[0]:.3f}s, esperado ~{WINDOW_PAD_S}s"
    )
    assert track.n_voiced >= MIN_VOICED_FRAMES, (
        f"{track.n_voiced} frames voiced de {track.n_frames}"
    )
```

E troque a linha de import logo acima (`from karaoke.scorer import track_from_word_timing`) por:

```python
from karaoke.scorer import WINDOW_PAD_S, track_from_word_timing
```

- [ ] **Step 2: Rodar e ver vermelho**

Run: `python -m pytest tests/test_scorer.py -q -k karaoke_ataques_vem_do_audio`
Expected: FAIL com `ImportError: cannot import name 'WINDOW_PAD_S'`. Se passar, pare: algo já mudou no módulo.

- [ ] **Step 3: Escrever os dois testes de janela e o de validação**

Acrescente ao **fim** de `tests/test_scorer.py`:

```python
def test_karaoke_janela_exclui_ataque_fora_do_gabarito():
    """Um burst 3s depois da ultima palavra existe no audio mas NAO na referencia.
    Controle: o detector sobre o audio inteiro acha 6 — a janela e quem tira 1."""
    times = TIMES + [6.0]
    freqs = FREQS + [262.0]
    audio = bursts(times, freqs)
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]        # so as 5 primeiras: 6.0 fica de fora

    inteiro = track_from_audio(audio, SR)
    assert len(inteiro.onsets) == 6, (
        f"controle: detector achou {len(inteiro.onsets)} de 6 bursts no audio inteiro"
    )
    ref = track_from_word_timing(words, audio, SR)
    assert len(ref.onsets) == 5, (
        f"janela deixou passar {len(ref.onsets)} ataques de 5 palavras"
    )


def test_karaoke_folga_captura_o_primeiro_ataque(monkeypatch):
    """Recorte que comeca EM CIMA do primeiro burst nao ve o RMS subir e perde o
    ataque. Sabotagem: WINDOW_PAD_S = 0 tem que ficar vermelho (medido em
    2026-09-12 no job real: pad 0 pega 4 de 5)."""
    import karaoke.scorer as mod
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]
    audio = bursts(TIMES, FREQS)

    com_folga = track_from_word_timing(words, audio, SR)
    assert len(com_folga.onsets) == len(TIMES), (
        f"com folga: {len(com_folga.onsets)} de {len(TIMES)}"
    )

    monkeypatch.setattr(mod, "WINDOW_PAD_S", 0.0)
    sem_folga = track_from_word_timing(words, audio, SR)
    assert len(sem_folga.onsets) < len(TIMES), (
        f"controle negativo nao ficou vermelho: pad 0 ainda pegou "
        f"{len(sem_folga.onsets)} de {len(TIMES)} — a folga nao esta sendo testada"
    )


def test_karaoke_gabarito_sem_end_ou_janela_vazia_e_erro():
    audio = bursts(TIMES, FREQS)
    with pytest.raises(ValueError, match="end"):
        track_from_word_timing([{"word": "um", "start": 0.3, "score": 1.0}], audio, SR)
    # gabarito inteiro depois do fim do audio: janela recortada ao audio fica vazia
    fora = [{"word": "um", "start": 50.0, "end": 50.3, "score": 1.0}]
    with pytest.raises(ValueError, match="janela"):
        track_from_word_timing(fora, audio, SR)
```

E em `test_karaoke_pontua_contra_si_mesmo`, troque a última linha:

```python
    assert r.total >= 95.0, f"karaoke contra si mesmo deu {r.total:.1f}"
```

(era `>= 80.0`; o spec mede 100,0 no job real — 80 deixava passar a versão antiga em fixture sintética).

- [ ] **Step 4: Rodar e ver vermelho**

Run: `python -m pytest tests/test_scorer.py -q -k karaoke`
Expected: os 4 testes novos/retargetados FALHAM (ImportError de `WINDOW_PAD_S` ou `AssertionError`). Os 3 que sobram (`vazio`, `fora_de_ordem`, `pontua_contra_si_mesmo`) podem passar ou falhar — não importa ainda.

- [ ] **Step 5: Implementar**

Em `karaoke/scorer.py`, logo abaixo de `WEIGHTS = {...}` (linha 85), acrescente:

```python
# Folga em torno de [words[0].start, words[-1].end] no modo karaoke. O detector
# precisa ver o RMS SUBIR: recorte que comeca em cima do primeiro ataque perde
# esse ataque (medido em 2026-09-12 no job mimic_gab_01: pad 0 pega 4 de 5;
# 0,05-0,2 pega 5 de 5). Tambem absorve parte do erro de ~200ms do MFA.
WINDOW_PAD_S = 0.1
```

Substitua `track_from_word_timing` inteira (da linha `def` até o `return ReferenceTrack(...)` final, fim do arquivo) por:

```python
def track_from_word_timing(words: list[dict], samples: np.ndarray,
                           sr: int) -> ReferenceTrack:
    """Referencia do modo karaoke: `track_from_audio` sobre o RECORTE do vocal
    isolado em [words[0].start - WINDOW_PAD_S, words[-1].end + WINDOW_PAD_S].
    O gabarito (work/jobs/<id>/05_alignment/word_timing.json) so valida e janela.

    Decisao (a) do spec, emenda 2026-09-12: antes, ref.onsets eram INICIOS DE
    PALAVRA (71 no job de teste) contra ATAQUES do detector no take (163 no mesmo
    audio) — populacoes diferentes, self-score ~54 com ritmo morto. Agora os dois
    lados passam pela mesma extracao: self-score 100,0 no job real.

    Os onsets devolvidos sao RELATIVOS ao inicio da janela; score() compara
    intervalos e contagens, nunca instantes absolutos.

    ponytail: teto documentado, NAO desta funcao — take deslocado no tempo da 62,1
    porque _mad_intervalos e posicional (160+ ataques, um a mais no comeco desalinha
    o resto); take com 1 clique de botao da 48,8 porque track_from_audio normaliza
    por pico de amostra. Os dois sao decisao de spec seguinte (F1 + andamento;
    envoltoria RMS ou vad.py no take).
    """
    if not words:
        raise ValueError("word_timing vazio: gabarito sem palavras nao produz referencia")

    starts = np.asarray([float(w["start"]) for w in words], dtype=np.float64)
    if np.any(np.diff(starts) < 0):
        fora = int(np.sum(np.diff(starts) < 0))
        raise ValueError(
            f"word_timing nao e monotonico: {fora} de {len(starts) - 1} pares fora de ordem"
        )
    if "end" not in words[-1]:
        raise ValueError("word_timing sem 'end' na ultima palavra: nao da para janelar")

    dur = len(samples) / sr
    t0 = max(0.0, float(starts[0]) - WINDOW_PAD_S)
    t1 = min(dur, float(words[-1]["end"]) + WINDOW_PAD_S)
    if t1 <= t0:
        raise ValueError(
            f"janela do gabarito [{t0:.2f}s, {t1:.2f}s] vazia dentro de {dur:.2f}s de audio"
        )
    return track_from_audio(samples[int(t0 * sr):int(t1 * sr)], sr)
```

- [ ] **Step 6: Rodar os testes do scorer e ver verde**

Run: `python -m pytest tests/test_scorer.py -q`
Expected: todos passam. Conte: o arquivo tinha N testes antes (Step 2 imprime); agora tem N + 3. Se `test_karaoke_folga_captura_o_primeiro_ataque` falhar na asserção do **controle negativo** (pad 0 ainda pega 5 de 5 na fixture sintética), **pare e reporte com o número** — não mude a fixture nem a folga para forçar o vermelho.

- [ ] **Step 7: Suíte inteira do scorer em primeiro plano**

Run: `python -m pytest tests/test_scorer.py tests/test_onset.py tests/test_score_route.py -q`
Expected: tudo verde. Anote "X passed" e cole no relatório.

- [ ] **Step 8: Re-derivar o self-score no job real (número do spec é alegação até aqui)**

O job `mimic_gab_01` vive no worktree irmão, `work/` é gitignored. Rode a partir da raiz deste worktree:

```bash
python -X utf8 - <<'EOF'
import json, numpy as np, soundfile as sf
from pathlib import Path
from karaoke.scorer import score, track_from_audio, track_from_word_timing
job = Path(r"C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\.claude\worktrees\mimic-party-discord-logic-4b5f14\work\jobs\mimic_gab_01")
words = json.loads((job / "05_alignment" / "word_timing.json").read_text(encoding="utf-8"))
x, sr = sf.read(job / "03_vocals_clean" / "vocals_raw.wav", dtype="float32")
if x.ndim > 1: x = x.mean(axis=1)
ref = track_from_word_timing(words, x, sr)
take = track_from_audio(x, sr)
r = score(ref, take)
print(f"palavras={len(words)} onsets_ref={r.n_onsets_ref} onsets_take={r.n_onsets_take} "
      f"melody={r.melody:.1f} rhythm={r.rhythm:.1f} attacks={r.attacks:.1f} total={r.total:.1f}")
EOF
```

Expected: `total` ≥ 95 (spec: 100,0) e `onsets_ref` da mesma ordem de `onsets_take` (~160, não 71). Cole a linha inteira no relatório. Se os arquivos não existirem, reporte o caminho que faltou — não invente número.

- [ ] **Step 9: Commit**

```bash
git add karaoke/scorer.py tests/test_scorer.py docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md docs/superpowers/plans/2026-09-12-karaoke-ref-janela-audio.md
git commit -m "fix(scorer): modo karaoke extrai a referencia do audio no recorte do gabarito (decisao a)

Antes, ref.onsets eram inicios de palavra (71) contra ataques do detector no
take (163): populacoes diferentes, self-score ~54, ritmo morto. Agora
track_from_word_timing valida o gabarito, recorta [t0-0.1, t1+0.1] e delega a
track_from_audio. Self-score no job real: 100,0. Deslocado 62,1 e clique 48,8
ficam documentados como teto pre-existente do ritmo posicional / normalizacao
por pico — decisao de spec seguinte.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Notas de execução

- A página `web/mimic.html` mostra `n_onsets_ref` na auditoria; no modo karaoke esse número passa de 71 para ~160. Item 2 do checklist manual do plano anterior ("auditoria mostra 71 ataques na ref") fica obsoleto — é consequência, não bug, e não se toca na página.
- `RHYTHM_TOL_FLOOR_S = 0.050` foi calibrado quando o intervalo mediano da referência karaoke era 0,140 s (entre palavras). Com ataques do detector o intervalo mediano muda; a tolerância é relativa (`RHYTHM_TOL_RATIO × mediana`) então se ajusta sozinha. Não recalibrar aqui.
- **Nota de execução (2026-09-12):** o Step 8 esperava `total >= 95` no job real e mediu
  **53,1** (`palavras=71 onsets_ref=164 onsets_take=163 melody=73.8 rhythm=0.0
  attacks=99.4`). O "100,0" da tabela de referência era janela contra a própria janela —
  tautologia, re-derivada como controle (100,0). O implementador parou antes do commit por
  contradição entre a mensagem pré-escrita e a medição; decisão: commitar com a mensagem
  corrigida. Os testes sintéticos (self ≥ 95) passam porque a fixture tem 0,2 s de
  pré-vocal e 5 ataques — não reproduzem o teto posicional. Spec corrigido na mesma sessão.
- **Revisão final (2026-09-12):** o texto dos Steps 3, 5 e 9 ('80 deixava passar a versão
  antiga', 'self-score 100,0 no job real' no docstring e na mensagem de commit) está
  **superado** pelos números acima — a versão antiga também dava 100 na fixture sintética, e
  o 100 no job real é janela contra a própria janela. Não copie o docstring do Step 5; o
  commitado (`1d003054`) é o correto. O 'pad 0 pega 4 de 5' foi re-derivado na fixture, não
  no job real.
