# Relatório da onda de correção final

Data: 2026-08-25 · Branch: `claude/pesquisa-fundos-letras-musicais-e67132`
Base: `d9abd034` → HEAD `50cec72f` (7 commits)

Todas as oito descobertas (F1–F8) foram corrigidas. Uma nona, bloqueante,
apareceu ao verificar a F3 e foi corrigida junto — está descrita abaixo.

---

## F1 — CRÍTICA: `onsets_from_wav` lia estéreo como mono

**Commit:** `76b36722` `fix(bounce): corrige o tempo dobrado dos onsets em WAV estereo`

`karaoke/bounce.py:onsets_from_wav` montava os frames RMS a partir do buffer
bruto (`nframes × canais` amostras intercaladas) enquanto `hop`/`win` saíam só
do sample rate. Cada índice de frame valia `canais` vezes o tempo real.

Correção: downmix pelo número real de canais do arquivo, com o frame parcial do
fim do buffer descartado defensivamente:

```python
canais = wf.getnchannels()
...
if canais > 1:
    sobra = len(audio) % canais
    if sobra:
        audio = audio[:-sobra]
    audio = audio.reshape(-1, canais).mean(axis=1)
```

### Evidência TDD (teste escrito primeiro, visto vermelho)

O teste antigo gerava `setnchannels(1)` — uma forma que o pipeline nunca produz
(`scripts/01_media_prep.py:55,69` grava com `-ac 2`, então o `no_vocals.wav` do
Demucs, única entrada desta função em `scripts/09_video_rendering.py:557`, é
estéreo) — e afirmava só a contagem. Verde sobre uma função quebrada.

O novo é parametrizado em 1 e 2 canais e afirma o **tempo** de cada clique.
Rodado ANTES da correção, com 4 cliques plantados em 0.5/1.5/2.5/3.5 s:

```
FAILED test_onsets_from_wav_acha_os_cliques_no_tempo_certo[2]
AssertionError: 2 canal(is): clique em 0.5s detectado em 0.970s (erro +0.470s)
```

O caso `[1]` (mono) passava — exatamente o motivo de o defeito ter sobrevivido.
Depois da correção: `10 passed` em `tests/test_bounce.py`, os dois canais verdes.

**Controle negativo:** o vermelho acima **é** o controle negativo (o teste viu a
função sabotada, que era o estado real do código, antes de existir a correção).

### Fora de escopo, confirmado presente

`scripts/05c_onset_dtw_align.py` e `scripts/08_onset_dtw.py` carregam o mesmo
defeito de leitura de canais, em outra entrada. **Não foram tocados**, conforme
instruído. Continuam quebrados se a entrada deles for estéreo.

---

## F2 — CRÍTICA: PNG de fundo corrompido quebrava o render para sempre

**Commit:** `2962e755` `fix(render): PNG de fundo corrompido nao pode mais matar o render`

Duas metades, ambas corrigidas:

1. `scripts/08b_background_image.py` — o `except` agora faz
   `out.unlink(missing_ok=True)` antes de avisar. Sem isso, um `shutil.copy2`
   interrompido no meio deixava um PNG truncado que o cache no topo do `main()`
   (que só olha `exists()`) reusaria em toda execução seguinte, para sempre.
2. `scripts/09_video_rendering.py` — ao pegar `CalledProcessError` com PNG de
   fundo em uso, refaz **uma vez** com `bg_png=None` e sem `sendcmd`, logando
   que caiu para o fundo chapado e o stderr do ffmpeg como motivo. Se o chapado
   também falhar, sai 1 como antes. Sem PNG de fundo (`bg_png is None`) o
   comportamento é idêntico ao anterior — sai 1 direto, sem retentativa inútil.

### Teste da retentativa: não feito, e por quê

A lógica de retentativa vive **dentro do `main()`** de
`scripts/09_video_rendering.py`, alcançável só depois de ~500 linhas que exigem
um job inteiro montado no disco (`word_timing.json`, `karaoke.ass`,
`no_vocals.wav`, `ffprobe` real). Não há como exercitá-la no nível de
`build_render_cmd`, que é puro e não conhece `subprocess`. Nenhum teste foi
adicionado a `tests/test_render_cmd.py` para esse caminho — o que lá existiria
seria uma afirmação sobre o comando chapado, que já é
`test_sem_fundo_cai_no_chapado_e_sem_sendcmd`, e não sobre a retentativa.

Verificado por leitura do fluxo e pelo smoke real do ffmpeg descrito na F5 (que
prova que o ramo ilustrado monta e roda; o ramo chapado é o mesmo comando que os
testes já cercam).

---

## F3 — `server.py` não rodava o estágio novo

**Commit:** `82edd87b` `fix(server): registra o estagio 08b e repara o kpaths.song_wav ausente`

`08b_background_image.py` registrado imediatamente antes de
`09_video_rendering.py`, mesma posição relativa do `run_pipeline.py`, com a forma
de dict do `server.py` (que difere do `run_pipeline.py`: leva `outputs` e
`timeout` além de `id`/`name`/`cmd`).

Medido depois da mudança:

```
_build_steps(aligner="mfa"):  14 estágios
  ... 8 Onset DTW Alignment, 9 Background Illustration, 10 Video Rendering, 11 Quality Assurance ...
_build_steps(aligner="sofa"): 16 estágios
```

### Bloqueante encontrado ao verificar (não estava na lista de findings)

`server.py:95` cita `kpaths.song_wav`, que **não existe** em `karaoke/paths.py`.
`_build_steps` estourava `AttributeError` no **primeiro** dict — antes de
qualquer estágio rodar. Ou seja: `python server.py` não rodava o 08b, mas
também não rodava nenhum outro estágio.

Registrar o 08b e parar aí seria entregar um verde falso, então o acessor foi
acrescentado apontando para onde `scripts/01_media_prep.py:49` **de fato** grava
(`input_job_dir(job_id) / "song.wav"`), não para um layout inventado. Medição:
`server.py` cita 15 acessores `kpaths.X`; 1 estava ausente, agora 0.

### Terceiro ponto, consequência direta do registro

`server.py` fazia `if step["id"] == 10:` para ler o `qc.json`. Os `id` são
renormalizados (`s["id"] = i + 1`) no fim de `_build_steps`, então inserir o 08b
deslocaria o Quality Assurance de 10 para 11 e o guard passaria a apontar para o
Video Rendering. Amarrado ao nome (`step["name"] == "Quality Assurance"`), que
não anda — e que já estava errado no caminho SOFA, onde o QA cai em 12.

---

## F4 — a cerca do contrato cobria um entry point só

**Commit:** `041af482` `test: estende a cerca aos dois entry points e corrige tres testes falsos`

`tests/test_paths_contract.py` agora deriva a lista da **união deduplicada** de
`run_pipeline.py` e `server.py`, e inclui os **próprios entry points** como
alvos (eles também citam `kpaths.X`, e foi exatamente ali que o `song_wav`
ausente vivia).

### Cobertura medida

| | antes (só `run_pipeline.py`) | depois (união + entry points) |
|---|---|---|
| alvos na cerca | 17 | **23** (21 scripts + 2 entry points) |
| examinados no disco | 17 | **21** |
| pulados com motivo | 0 | **2** |
| referências `kpaths.X` únicas examinadas | 54 | **76** |
| acessores ausentes | 0 | **0** |

Novos no fence: `10_quality_assurance.py`, `12_user_notification.py`,
`run_sofa.py`, `run_rosvot.py`, `run_pipeline.py`, `server.py`.

Os dois pulados são `scripts/run_sofa.py` e `scripts/run_rosvot.py`, que o
`server.py` invoca e que não existem no repositório. Eles **não somem em
silêncio** — o motivo do skip nomeia o entry point:

```
SKIPPED [1] scripts/run_rosvot.py nao existe no disco — referenciado por server.py
SKIPPED [1] scripts/run_sofa.py nao existe no disco — referenciado por server.py
```

Guards de cardinalidade: o `assert dono` original foi mantido, e foi acrescentado
`test_o_fence_cobre_os_dois_entry_points`, que exige contribuição dos dois — se a
extração quebrar em um deles, o `parametrize` encolhe e todo o resto ficaria
verde por vacuidade sem nada acusar.

---

## F5 — a deriva prometida no spec, implementada

**Commit:** `1172a0f7` `feat(bounce): implementa a deriva lenta (Ken Burns) prometida no spec`

`build_sendcmd` ganhou `duration: float = None` (default = sem deriva, todo
caller antigo continua válido) e emite uma varredura linear de `crop x` /
`crop y` ao longo do vídeo, no **mesmo** `crop` do pulso — o plano proíbe
empilhar `zoompan`. `scripts/09_video_rendering.py` passa a duração real
(a mesma que já vinha do `ffprobe` e alimenta o `-t`).

### O detalhe que quase inviabilizava um diff pequeno

Com o crop de repouso igual à fonte (`base_w × base_h` == `WORK_W × WORK_H`), o
clamp `x + w <= WORK_W` força `x = 0` — deriva zero. Por isso, **e só quando a
deriva está ligada**, o crop de repouso encolhe `DRIFT_MARGIN` (4%), abrindo
`1408-1350 = 58 px` em x e `792-760 = 32 px` em y para varrer. O clamp é medido
contra a **maior** largura comandada (a de repouso); a do pulso é menor e cabe
por consequência. Tudo par, ponta a ponta.

### Evidência TDD e controles negativos

Teste escrito antes da implementação, visto vermelho com
`TypeError: build_sendcmd() got an unexpected keyword argument 'duration'`.
Depois de implementado, dois controles negativos explícitos:

| sabotagem | resultado |
|---|---|
| `DRIFT_MARGIN = 0.0` (deriva sem folga) | **vermelho**: `x nao se moveu em 61 comandos: (0.0, 0) -> (60.0, 0)` |
| clamp removido (`_par(max_x * frac * 1.6)`) | **vermelho**: `x=60 + w=1350 estoura 1408` |
| restaurado | `10 passed` |

### Smoke contra o ffmpeg real

O `sendcmd` comandando `crop x`/`crop y` nunca tinha sido exercitado. Rodado
contra o binário do sistema, com PNG de teste, 2 s:

```
0.000 crop x 0, crop y 0;
0.400 crop w 1308, crop h 736;
0.580 crop w 1350, crop h 760;
...
2.000 crop x 58, crop y 32;

rc = 0
mp4 bytes = 198661
```

Sintaxe aceita, comandos em ordem crescente, MP4 válido. `x` chega ao limite
exato da folga (58) sem estourar.

---

## F6 — três testes falsos

**Commit:** `041af482` (mesmo da F4)

1. `tests/test_paths_contract.py` — `assert (input_job / "song.wav").parent ==
   input_job` era verdadeiro para qualquer `Path`, independente do código sob
   teste, dentro do próprio teste que cerca o defeito do fix round 1. Removido.
2. `tests/test_background.py` — `test_letra_crua_nao_vaza_para_o_prompt_de_imagem`
   passava um brief constante que nunca contivera a letra: verdadeiro por
   construção. Reescrito como
   `test_letra_crua_nao_vaza_para_o_no_do_comfyui`, que exercita a fronteira
   real — captura o payload que `generate_image` envia e afirma sobre o texto
   que `_inject_prompt` de fato pôs no nó do workflow. Declara quantas palavras
   da letra examinou (`{len(vazadas)} de {len(palavras)}`).
   **Controle negativo:** com o Ollama dublado devolvendo a própria letra como
   brief (o que um passo de brief quebrado faria), fica vermelho:
   `5 de 5 palavras da letra crua chegaram ao gerador de imagem: ['andei',
   'caminhos', 'tortos', 'nascer', 'ipanema']`. Restaurado: verde.
3. `tests/test_pipeline_e2e.py` — exigia `07_video/karaoke_preview.mp4`, saída de
   `scripts/08_render_video.py` que este branch apagou, e usava uma fixture
   `job_dir_path` que nunca existiu. Marcado
   `@pytest.mark.xfail(run=False)` com motivo nomeando o renderizador morto e o
   que o substitui (`09_video_rendering.py` / `kpaths.output_video()`).
   Isolado, o arquivo reporta `1 xfailed`.

---

## F7 — três limpezas

**Commit:** `074e46cf` `fix: limpa tres arestas pequenas do caminho de fundo`

- `karaoke/paths.py` — `input_video` e `input_thumb` removidos (mortos desde a
  Task 5; só o `test_paths_contract.py` os mantinha vivos), e retirados da lista
  desse teste. A lista ganhou um guard de cardinalidade
  (`assert len(novos) >= 5`) para não encolher em silêncio.
- `karaoke/render_cmd.py` — `FLAT_BG` agora sai de `OUT_W`/`OUT_H`
  (`f"color=c=#08090f:s={OUT_W}x{OUT_H}"`), com as constantes reordenadas.
- `karaoke/background.py` — `generate_image` inclui `img.get("subfolder", "")`
  no caminho de origem. `Path / ""` é no-op, então o caso vazio (o comum) segue
  byte a byte idêntico.

---

## F8 — README

**Commit:** `50cec72f` `docs: acerta a contagem de estagios e declara o que nunca foi executado`

- **Contagem.** Os três números batem agora, derivados do `run_pipeline.py`:
  **14 estágios por execução**, **17 invocações de script registradas** (porque
  os estágios 4–6 têm duas variantes mutuamente exclusivas), **`id` de 1 a 14**.
  A lista de estágios foi refeita a partir dele — a antiga não batia com nenhum
  nome real e não continha o 08b. Acrescentada a diferença real do `server.py`,
  que monta uma lista parecida mas não igual (MFA em um estágio só, mais QA e
  notificação, e dois scripts que não existem no caminho SOFA).
- **Dois valores do ComfyUI.** Tabela nova documentando `COMFY_PROMPT_NODE`
  (`"6"`) e a porta em `COMFY_HOST` (`8188`, não verificada), com a consequência
  de cada um estar errado: `KeyError` / conexão recusada → fallback silencioso e
  permanente para o fundo chapado, com o job terminando normalmente.
- **Frase honesta**, em destaque, sem suavizar: o caminho ilustrado nunca foi
  executado contra um ComfyUI real, nenhum job completou neste repositório, e a
  primeira execução é também a primeira validação.
- A linha `scripts/ (01-09)` foi corrigida.

---

## Resultado dos testes

Comando: `python -m pytest tests/ --ignore=tests/integration --ignore=tests/test_ass_builder.py`

| | baseline (`d9abd034`) | depois (`50cec72f`) | delta |
|---|---|---|---|
| failed | 1 | 1 | 0 |
| passed | 71 | 75 | **+4** |
| xfailed | 1 | 1 | 0 |
| errors | 169 | 183 | **+14** |

**Reconciliação dos deltas (as partes fecham com o total):**

- `+4 passed` = `tests/test_bounce.py` foi de 6 para 10 testes (1 teste de onset
  virou 2 parametrizados, mais 3 testes de deriva).
- `+14 errors` = `tests/test_paths_contract.py` foi de 19 para 26 casos, e nesse
  arquivo **todo** caso erra na suite completa (setup + teardown = 2 erros por
  caso). 7 × 2 = 14. Nenhum erro novo de outra natureza.

O `1 failed` é `test_critical_pipeline.py::TestNormaliseLyrics::test_contractions_expanded`,
pré-existente e intocado. O erro de coleta de `tests/test_ass_builder.py` e o
ruído de teardown são pré-existentes. **Nada que eu introduzi falha.**

### Os 183 erros não são só ruído — a cerca não roda

Isolado o culpado por bisseção:

```
suite completa                                  → 183 errors
suite completa SEM test_background.py           → 183 errors  (não é ele)
test_bounce.py + test_paths_contract.py         → 34 passed, 2 skipped, 0 errors
test_critical_pipeline.py + test_paths_contract → 1 failed, 57 passed, 55 errors
```

`tests/test_critical_pipeline.py` fecha o buffer compartilhado de
stdout/stderr (`ValueError: I/O operation on closed file`, em
`tempfile.py:500`, no setup da fixture `tmp_path`) e envenena todo teste que
use `tmp_path` depois dele na ordem alfabética. Consequência concreta:
**os 26 casos de `tests/test_paths_contract.py` erram — nenhum executa — na
suite completa.** A cerca do contrato, que é justamente o assunto da F4, não é
exercitada pelo comando de verificação padrão.

Rodada isolada (ou antes do poluidor), ela é verde:
`24 passed, 2 skipped` — os 24 com denominador declarado na tabela da F4.

Isto é **pré-existente** (os 169 erros do baseline são o mesmo fenômeno) e está
**fora do escopo** desta onda, então não foi corrigido. Mas é a maior concern
aberta: as duas medições da F4 acima valem para a execução isolada, não para o
comando padrão.

---

## Arquivos alterados

```
README.md                        |  91 +++++++++++-------
karaoke/background.py            |   5 +-
karaoke/bounce.py                |  72 ++++++++++++---
karaoke/paths.py                 |  12 +--
karaoke/render_cmd.py            |   6 +-
scripts/08b_background_image.py  |   5 +
scripts/09_video_rendering.py    |  23 ++++-
server.py                        |  14 +++-
tests/test_background.py         |  48 ++++++++--
tests/test_bounce.py             |  92 +++++++++++++++----
tests/test_paths_contract.py     |  69 +++++++++-----
tests/test_pipeline_e2e.py       |  11 +++
```

Nenhum `.pyc` foi commitado — o ruído de `__pycache__` no `git status` é
pré-existente e continua fora do índice (todo `git add` usou caminho exato).

---

## Concerns

1. **A cerca do contrato não roda na suite completa.** Detalhado acima.
   `tests/test_critical_pipeline.py` mata o stdout compartilhado e derruba os 26
   casos de `test_paths_contract.py` para ERROR. Pré-existente, fora de escopo,
   mas anula na prática o valor da F4 sob o comando de verificação padrão.
2. **`server.py` estava morto antes do estágio 1** e ninguém tinha notado —
   `kpaths.song_wav` ausente. Corrigido, mas indica que o app nunca foi
   executado neste branch. Vale rodar `python server.py` até o primeiro estágio
   antes de considerar a F3 fechada de verdade.
3. **`run_sofa.py` e `run_rosvot.py` não existem.** `server.py` os invoca no
   caminho `--aligner sofa`. Esse caminho está quebrado no app (o
   `run_pipeline.py` usa `03_forced_align_sofa.py` / `03b_rosvot_inference.py`,
   que existem). A cerca agora pula os dois com motivo nomeado, mas pular não é
   consertar.
4. **`05c_onset_dtw_align.py` e `08_onset_dtw.py` continuam com o bug de canais
   da F1**, conforme instruído. `08_onset_dtw.py` roda em toda execução do
   pipeline.
5. **A deriva nunca foi vista em movimento por um olho humano.** O ffmpeg aceita
   a sintaxe e produz MP4 (medido), mas se 4% de varredura em 3m30 é "lento e
   agradável" ou "imperceptível demais para valer" só a primeira execução real
   diz. `DRIFT_MARGIN` e `DRIFT_STEP_SECONDS` estão como constantes no topo de
   `karaoke/bounce.py`, prontos para ajuste.
6. **A retentativa da F2 não tem teste automatizado** — justificativa completa na
   seção da F2.
