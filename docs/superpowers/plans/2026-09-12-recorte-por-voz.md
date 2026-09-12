# Recorte por atividade de voz no take — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `track_from_audio` recorta as duas pontas do áudio ao primeiro e último trecho com
voz ANTES de normalizar por pico, para que clique de botão e pré-vocal não entrem na nota.

**Architecture:** Uma função pura `trim_to_voice(samples, sr)` em `karaoke/scorer.py`,
máscara `rms > VOICE_FRAC × p95(rms)` sobre o envelope de `compute_rms`, suavizada e
segmentada pelas funções puras que já existem em `karaoke/vad.py`. `ReferenceTrack` ganha
`trim_start_s`/`trim_end_s`; a rota expõe os do take. Spec: emenda 2026-09-12 (3) em
`docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md`.

**Tech Stack:** Python 3, numpy, pytest. Sem dependência nova.

## Global Constraints

- `karaoke/scorer.py` continua **puro**: sem subprocess, sem I/O de arquivo.
- Não alterar `karaoke/vad.py` nem `karaoke/onset.py` (pipeline depende deles; `tests/test_critical_pipeline.py` importa `_smooth_mask`/`_mask_to_segments` de `vad.py` — as assinaturas ficam como estão).
- Não desativar teste (`.skip`/`.only`/`xit`) — hook `veto-edit.mjs` bloqueia.
- Comentário de atalho deliberado usa o prefixo `# ponytail:` e nomeia o teto e o upgrade.
- Rodar testes em **primeiro plano** e colar a saída; não mandar para background.
- Números publicados vêm com denominador ("5 de 5", "40 de 164"), nunca soltos.
- Comandos de teste, a partir da raiz do worktree (`C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\.claude\worktrees\diffusion-multi-angle-gen-7a276a`): `python -X utf8 -m pytest tests/test_scorer.py -q -p no:cacheprovider`. Se `import librosa` falhar, usar `C:\Users\Katz\miniforge3\envs\karaoke_env\python.exe` no lugar de `python` e dizer qual foi usado.
- Commits terminam com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: `trim_to_voice` dentro de `track_from_audio`, com cerca sintética e medição no job real

**Files:**
- Modify: `karaoke/scorer.py` (imports linha 15; `ReferenceTrack` linhas 25-38; `track_from_audio` linhas 41-77; bloco de knobs novo antes de `track_from_audio`)
- Modify: `tests/test_scorer.py` (`test_silencio_nao_produz_contorno` linhas 67-73; `test_ritmo_deslocamento_global_e_estimado_nao_assumido` linhas 346-359; dois testes novos ao fim do arquivo)

**Interfaces:**
- Consumes: `karaoke.onset.compute_rms(samples, sr) -> (rms, frame_dur)`, `karaoke.onset.HOP_MS` (= 10), `karaoke.vad._smooth_mask(mask: list[bool], hop_ms, min_speech_ms, min_silence_ms) -> list[bool]`, `karaoke.vad._mask_to_segments(mask, hop_ms, pad_ms, total_duration) -> list[VADSegment]` (cada um com `.start`/`.end` em segundos).
- Produces: `trim_to_voice(samples: np.ndarray, sr: int) -> tuple[np.ndarray, float, float]` (recorte, segundos removidos no início, segundos removidos no fim); `ReferenceTrack.trim_start_s: float`, `ReferenceTrack.trim_end_s: float`; constantes `VOICE_FRAC`, `VOICE_MIN_SPEECH_MS`, `VOICE_MIN_SILENCE_MS`, `VOICE_PAD_MS`.

- [ ] **Step 1: Escrever os dois testes novos (falhando) ao fim de `tests/test_scorer.py`**

```python
# ── emenda 3: recorte por atividade de voz ──────────────────────────────────
from karaoke.onset import compute_rms, detect_onsets


def test_clique_no_inicio_nao_afoga_o_vocal():
    """Clique de botao (5 ms a 1,0) antes de um vocal a 0,02 de pico. Normalizado
    pelo pico do CLIQUE, o vocal cai abaixo de ENERGY_MIN e o detector perde os
    ataques — no job real 40 de 164 sobrevivem, rhythm 38,2 (medido 2026-09-12).
    O recorte por voz tira o clique ANTES da normalizacao."""
    vocal = bursts(TIMES, FREQS) * (0.02 / 0.6)
    take = np.concatenate([np.zeros(int(0.5 * SR), dtype=np.float32), vocal])
    take[int(0.05 * SR):int(0.055 * SR)] = 1.0

    # controle negativo: sem o recorte, normalizar pelo clique afoga o vocal
    rms, fd = compute_rms(take / float(np.abs(take).max()), SR)
    sem_recorte = len(detect_onsets(rms, fd))
    assert sem_recorte < len(TIMES), (
        f"controle: sem recorte o detector ainda acha {sem_recorte} de {len(TIMES)} — "
        "a sabotagem nao sabotou, o teste nao prova nada"
    )

    track = track_from_audio(take, SR)
    assert track.trim_start_s > 0.055, (
        f"recorte comecou em {track.trim_start_s:.3f}s: o clique (0,050-0,055 s) ficou dentro"
    )
    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} com clique antes (sem recorte: {sem_recorte})"
    )


def test_recorte_tira_silencio_das_duas_pontas_e_desloca_os_ataques():
    """1 s de silencio antes e 1 s depois: os dois somem, os ataques ficam relativos
    ao recorte (o primeiro cai a ~VOICE_PAD_MS do inicio) e os intervalos nao mudam."""
    from karaoke.scorer import VOICE_PAD_MS
    base = bursts(TIMES, FREQS)
    take = np.concatenate([np.zeros(SR, dtype=np.float32), base, np.zeros(SR, dtype=np.float32)])
    track = track_from_audio(take, SR)
    direto = track_from_audio(base, SR)

    esperado_inicio = 1.0 + TIMES[0] - VOICE_PAD_MS / 1000
    assert abs(track.trim_start_s - esperado_inicio) <= 0.05, (
        f"trim_start_s {track.trim_start_s:.3f}s, esperado ~{esperado_inicio:.2f}s"
    )
    assert track.trim_end_s >= 0.9, f"trim_end_s {track.trim_end_s:.3f}s: o silencio do fim ficou"
    assert len(track.onsets) == len(TIMES), f"{len(track.onsets)} ataques de {len(TIMES)}"
    assert abs(track.onsets[0] - VOICE_PAD_MS / 1000) <= 0.05, (
        f"primeiro ataque em {track.onsets[0]:.3f}s, esperado ~{VOICE_PAD_MS / 1000}s"
    )
    np.testing.assert_allclose(np.diff(track.onsets), np.diff(direto.onsets), atol=0.02)
```

- [ ] **Step 2: Rodar os dois e confirmar que falham pelo motivo certo**

Run: `python -X utf8 -m pytest tests/test_scorer.py -q -p no:cacheprovider -k "clique_no_inicio or recorte_tira_silencio"`
Expected: 2 failed — `AttributeError: 'ReferenceTrack' object has no attribute 'trim_start_s'` no primeiro; `ImportError: cannot import name 'VOICE_PAD_MS'` no segundo. Se o controle negativo do primeiro (`sem_recorte < 5`) falhar, PARE e reporte: a fixture não sabota e o teste não vale.

- [ ] **Step 3: Implementar em `karaoke/scorer.py`**

Trocar a linha de import de `karaoke.onset` e acrescentar o de `vad`:

```python
from karaoke.onset import HOP_MS, compute_rms, detect_onsets
from karaoke.vad import _mask_to_segments, _smooth_mask  # puras; detect_voice le arquivo e capa em p50
```

Acrescentar os dois campos ao FIM de `ReferenceTrack` (depois de `n_octave_suspect`):

```python
    trim_start_s: float     # segundos removidos no inicio pelo recorte por voz (emenda 3)
    trim_end_s: float       # idem no fim; (0, 0) quando nao ha trecho de voz
```

Inserir, entre `ReferenceTrack` e `track_from_audio`:

```python
# ── Recorte por atividade de voz (spec, emenda 2026-09-12 (3)) ──────────────
# O take tem coisa que a referencia nao tem. Clique do botao: vira o pico da
# normalizacao e afoga o vocal abaixo de ENERGY_MIN (job real: 40 de 164 ataques,
# rhythm 38,2). Pre-vocal: 24 de 363 frames voiced em 11,6 s de "silencio" do stem
# contaminam o contorno (melody 86,8 no take inteiro; 100,0 sem o pre-vocal). Os
# dois somem recortando as pontas ao primeiro/ultimo trecho de voz ANTES de
# normalizar. Limiar relativo ao ENVELOPE (p95 do RMS), nao ao pico de amostra:
# um clique de 5 ms ocupa <= 3 frames em 6.000 e nao move o p95.
VOICE_FRAC = 0.10          # ponytail: fracao fixa (-20 dB de p95); intro sussurrada abaixo
                           # disso e perdida. Knob de calibracao — no job real 0,03-0,20 acham
                           # o mesmo inicio (11,86-11,88 s); so um take de mic real recalibra.
VOICE_MIN_SPEECH_MS = 150  # trecho mais curto nao e voz (clique, estalo)
VOICE_MIN_SILENCE_MS = 200
VOICE_PAD_MS = 100         # o detector precisa ver o RMS subir (mesma razao de WINDOW_PAD_S)


def trim_to_voice(samples: np.ndarray, sr: int) -> tuple[np.ndarray, float, float]:
    """Devolve (recorte, segundos removidos no inicio, segundos removidos no fim).
    Sem trecho de voz devolve o audio inteiro e (0, 0): silencio continua sendo
    populacao vazia visivel no resto do scorer, nao erro aqui."""
    dur = len(samples) / sr
    rms, _ = compute_rms(samples, sr)
    if len(rms) == 0:
        return samples, 0.0, 0.0
    thr = VOICE_FRAC * float(np.percentile(rms, 95))
    # _smooth_mask compara com `is True`: precisa de bool nativo, nao np.bool_
    mask = _smooth_mask([bool(v) for v in rms > thr], HOP_MS,
                        VOICE_MIN_SPEECH_MS, VOICE_MIN_SILENCE_MS)
    segs = _mask_to_segments(mask, HOP_MS, VOICE_PAD_MS, dur)
    if not segs:
        return samples, 0.0, 0.0
    t0, t1 = segs[0].start, segs[-1].end
    return samples[int(t0 * sr):int(t1 * sr)], t0, dur - t1
```

Em `track_from_audio`, logo depois de `samples = np.asarray(samples, dtype=np.float32)` e ANTES do comentário da normalização por pico:

```python
    samples, trim_start_s, trim_end_s = trim_to_voice(samples, sr)
```

E no `return ReferenceTrack(...)`, acrescentar:

```python
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
```

Atualizar a docstring de `track_from_audio` para: `"""Extrai ataques e contorno de f0 de um audio mono, depois de recortar as pontas ao trecho com voz (trim_to_voice)."""`

- [ ] **Step 4: Rodar os dois testes novos**

Run: `python -X utf8 -m pytest tests/test_scorer.py -q -p no:cacheprovider -k "clique_no_inicio or recorte_tira_silencio"`
Expected: 2 passed. Se `test_clique_no_inicio_nao_afoga_o_vocal` falhar em `trim_start_s > 0.055`, imprimir `track.trim_start_s` e os segmentos e reportar — não mexer em `VOICE_MIN_SPEECH_MS` para passar.

- [ ] **Step 5: Ajustar os dois testes existentes que a emenda muda**

Em `test_silencio_nao_produz_contorno`, acrescentar ao fim:

```python
    assert (track.trim_start_s, track.trim_end_s) == (0.0, 0.0), (
        f"silencio absoluto foi recortado: ({track.trim_start_s}, {track.trim_end_s})"
    )
```

Substituir `test_ritmo_deslocamento_global_e_estimado_nao_assumido` inteiro por:

```python
def test_ritmo_deslocamento_global_e_estimado_nao_assumido(ref):
    """Um deslocamento global de 0.45s entre os trens de ataque custa zero: o
    offset vem da correlacao cruzada. Controle negativo: sem alinhar (b=0) o
    casamento a 0.08s nao acha nada — 0.45 e escolhido para que o par nao
    alinhado mais proximo fique a 0.15s (0.9 vs 0.75), longe da tolerancia.
    Testado no nivel dos ataques: pre-roll de SILENCIO no audio e removido pelo
    recorte por voz (emenda 3) antes de chegar aqui; o fim-a-fim com coisa antes
    que o recorte nao tira (uma nota) e test_onset_espurio_antes_nao_derruba_abaixo_do_acaso."""
    from karaoke.scorer import _align_offset, _match_f1, MATCH_TOL_S
    deslocado = ref.onsets + 0.45
    b = _align_offset(ref.onsets, deslocado)
    assert abs(b - 0.45) <= MATCH_TOL_S, f"offset estimado {b:.3f}s, esperado 0.45s"
    f1_sem, n_sem = _match_f1(ref.onsets, deslocado)
    assert n_sem == 0, f"controle: sem alinhar casou {n_sem} de {len(TIMES)}"
    f1_com, n_com = _match_f1(ref.onsets, deslocado - b)
    assert n_com == len(TIMES), f"{n_com} de {len(TIMES)} casados depois de alinhar"
    assert f1_com >= 0.95, f"deslocamento de 0.45s custou F1 {f1_com:.2f}"
```

- [ ] **Step 6: Rodar a suíte do scorer inteira e a da rota**

Run: `python -X utf8 -m pytest tests/test_scorer.py tests/test_score_route.py tests/test_onset.py -q -p no:cacheprovider`
Expected: todos passam (eram 25 + 17 + 6 = 48; agora 50 em test_scorer.py + os demais). Colar a linha final `N passed`. Se qualquer teste antigo falhar, PARE e reporte nome + assert — não ajuste o teste.

- [ ] **Step 7: Medir no job real (aceite do spec)**

Gravar em `C:\Users\Katz\AppData\Local\Temp\claude\medir_recorte.py` e rodar com `python -X utf8 C:\Users\Katz\AppData\Local\Temp\claude\medir_recorte.py` a partir da raiz do worktree (com `PYTHONPATH` apontando para ela, se necessário):

```python
import json, numpy as np, soundfile as sf
from pathlib import Path
from karaoke.scorer import score, track_from_audio, track_from_word_timing, WINDOW_PAD_S
job = Path(r"C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\.claude\worktrees\mimic-party-discord-logic-4b5f14\work\jobs\mimic_gab_01")
words = json.loads((job / "05_alignment" / "word_timing.json").read_text(encoding="utf-8"))
x, sr = sf.read(job / "03_vocals_clean" / "vocals_raw.wav", dtype="float32")
if x.ndim > 1: x = x.mean(axis=1)
ref = track_from_word_timing(words, x, sr)
print(f"ref: {len(ref.onsets)} ataques, trim=({ref.trim_start_s:.2f}, {ref.trim_end_s:.2f})")
def linha(nome, take):
    r = score(ref, take)
    print(f"{nome:<22} ref={r.n_onsets_ref} take={r.n_onsets_take} casados={r.n_matched} "
          f"melody={r.melody:.1f} rhythm={r.rhythm:.1f} attacks={r.attacks:.1f} total={r.total:.1f} "
          f"trim=({take.trim_start_s:.2f}, {take.trim_end_s:.2f})")
t0 = max(0.0, words[0]["start"] - WINDOW_PAD_S); t1 = min(len(x)/sr, words[-1]["end"] + WINDOW_PAD_S)
win = x[int(t0*sr):int(t1*sr)]
linha("self (janela)", track_from_audio(win, sr))
linha("audio inteiro", track_from_audio(x, sr))
clique = x.copy(); i = int(0.05*sr); clique[i:i+int(0.005*sr)] = 1.0
linha("inteiro + clique", track_from_audio(clique, sr))
rng = np.random.default_rng(7)
bl = int(sr); blocos = [win[i:i+bl] for i in range(0, len(win)-bl, bl)]
rs = [score(ref, track_from_audio(np.concatenate([blocos[i] for i in rng.permutation(len(blocos))]), sr)).rhythm for _ in range(20)]
print(f"blocos embaralhados n=20 rhythm media={np.mean(rs):.1f} p95={np.percentile(rs,95):.1f}")
```

Expected (aceite do spec): `audio inteiro` melody ≥ 95 (antes 86,8) e `trim` do take em [11,5, 12,0]; `inteiro + clique` rhythm ≥ 95 e attacks ≥ 95 (antes 38,2 / 24,4); `self` 100; blocos p95 ≤ 60. Colar as cinco linhas literais no relatório. Se algum número ficar fora, NÃO ajustar knob: reportar o número e parar.

- [ ] **Step 8: Commit**

```bash
git add karaoke/scorer.py tests/test_scorer.py
git commit -m "feat(scorer): recorte por atividade de voz nas duas pontas antes de normalizar

Clique de botao virava o pico da normalizacao e afogava o vocal (job real: 40 de
164 ataques, rhythm 38,2); pre-vocal do take contaminava o contorno do pyin
(melody 86,8 no inteiro, 100,0 sem ele). trim_to_voice: mascara rms > VOICE_FRAC x
p95(rms) sobre o envelope do detector, suavizada por _smooth_mask/_mask_to_segments
de vad.py (puras; detect_voice le arquivo e capa em p50). ReferenceTrack ganha
trim_start_s/trim_end_s.

Medido no job mimic_gab_01: inteiro melody 86,8 -> <VALOR>, total 93,6 -> <VALOR>;
inteiro + clique rhythm 38,2 -> <VALOR>, attacks 24,4 -> <VALOR>; trim do take
<VALOR> s (words[0].start 11,69). Sintetico: clique + vocal a 0,02 perde ataques
sem recorte (controle negativo: <N> de 5) e pega 5 de 5 com.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Substituir cada `<VALOR>`/`<N>` pelo número medido nos passos 2 e 7. Mensagem com placeholder é falha.

---

### Task 2: Rota expõe o recorte do take; docstring e spec dizem o número novo

**Files:**
- Modify: `server_score_addendum.py` (dict do `jsonify` ao fim de `api_score`, ~linhas 133-146)
- Modify: `karaoke/scorer.py` (docstring de `track_from_word_timing`, parágrafo `ponytail: teto documentado, NAO desta funcao`)
- Modify: `docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md` (emenda 3, seção "Aceite")

**Interfaces:**
- Consumes: `ReferenceTrack.trim_start_s`, `ReferenceTrack.trim_end_s` (Task 1).
- Produces: campos `take_trim_start_s`, `take_trim_end_s` no JSON de `POST /api/score`.

- [ ] **Step 1: Rota**

No `jsonify({...})` de `api_score`, depois de `"n_voiced_take": take.n_voiced,`:

```python
            "take_trim_start_s": round(take.trim_start_s, 2),
            "take_trim_end_s": round(take.trim_end_s, 2),
```

Não há teste de rota que leia um 200 (os 17 de `tests/test_score_route.py` cobrem 400/404/413/503): este campo fica **sem cerca**, como `n_voiced_take`. Dizer isso no relatório e no commit; não dizer "rota fenceia".

- [ ] **Step 2: Docstring de `track_from_word_timing`**

Substituir o parágrafo que começa em `ponytail: teto documentado, NAO desta funcao` (até `decisao de spec seguinte.`) por:

```
    Clique de botao e pre-vocal do take (rhythm 38,2 e melody 86,8 no job real)
    foram fechados pela emenda 3: track_from_audio recorta as pontas ao trecho com
    voz antes de normalizar (trim_to_voice).
```

- [ ] **Step 3: Spec — números re-derivados**

Na emenda 3 do spec, seção "### Aceite (medido, não estimado)", acrescentar ao fim um parágrafo:

```
Re-derivado na implementação (commit `<sha do Task 1>`): inteiro melody <VALOR> / total
<VALOR>, trim do take <VALOR> s; inteiro + clique rhythm <VALOR> / attacks <VALOR>; blocos p95
<VALOR>; sintético clique <N> de 5 sem recorte → 5 de 5 com.
```

Preencher com os números do Task 1 (passos 2 e 7) e o sha do commit do Task 1 (`git log -1 --format=%h`).

- [ ] **Step 4: Rodar a suíte da rota e do scorer**

Run: `python -X utf8 -m pytest tests/test_scorer.py tests/test_score_route.py -q -p no:cacheprovider`
Expected: todos passam; colar `N passed`.

- [ ] **Step 5: Commit**

```bash
git add server_score_addendum.py karaoke/scorer.py docs/superpowers/specs/2026-09-10-scorer-mimic-karaoke-design.md
git commit -m "docs(scorer): rota expoe take_trim_*; docstring e spec dizem os numeros re-derivados do recorte

take_trim_start_s/take_trim_end_s no JSON de /api/score — sem cerca (nenhum teste
da rota le um 200), como n_voiced_take. Docstring de track_from_word_timing deixa
de apontar clique/pre-vocal como teto aberto.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
