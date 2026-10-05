# Jogo de karaokê — Etapa 1 (rodadas por trecho) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modo Karaokê no `party.html`. Cada rodada é um trecho de 20–30 s de uma música já processada, priorizando o refrão. Toca só a base, a letra acende palavra por palavra e a nota sai de `/api/score` recortado ao trecho.

**Architecture:** Regra dos trechos em Python puro (`karaoke/trechos.py`). Rotas novas num addendum no molde dos existentes. `/api/score` ganha `start`/`end`. No navegador, um componente de letra (`web/letra-trecho.js`) e a lógica da vez de karaokê (`web/karaoke-vez.js`), plugados no fluxo de rodadas do `party.html` sem tocar em audição, votação e placar.

**Tech Stack:** Python 3.12 + Flask + numpy/librosa/soundfile (já instalados no `.venv`), pytest, JS puro no navegador (sem build, sem dependência nova).

**Spec:** `docs/superpowers/specs/2026-10-05-karaoke-game-qualquer-musica-design.md`

## Global Constraints

- Testes rodam com `.venv/Scripts/python -m pytest` a partir de `karaoke-mfa-multi/`.
- Nenhuma dependência nova, nem Python nem JS.
- `TRECHO_MIN_S = 20.0`, `TRECHO_MAX_S = 30.0`, `PRE_ROLL_S = 2` (navegador), contagem de 3 s antes de cantar.
- Padrão de `pitch`: `oitava` no karaokê, `relativo` no imitar (já em `PITCH_DEFAULT`). Seletor de dificuldade com padrão **Normal** no modo Karaokê e **Fácil** no Imitar.
- Todo `job` vindo do cliente passa pela `REF_ID_RE` de `server_score_addendum.py` antes de virar caminho.
- Caminhos de job só via `karaoke/paths.py` (`kpaths`), nunca montados à mão.
- Estilo do repo: comentários e identificadores em português sem acento no código Python. Simplificação deliberada leva marcador `# ponytail:` com o teto e o gatilho de upgrade.
- Erros das rotas no formato `{"error": msg}` com status (helper `_erro` de `server_score_addendum.py`).

**Desvios conscientes do spec** (ambos registrados em comentário no código):
1. `MAX_TAKE_S` sobe de 30 para 35. O take inclui `PRE_ROLL_S` de pré-roll, e um trecho de 30 s viraria um take de 32 s cortado pelo ffmpeg. A validação de `end − start` usa `TRECHO_MAX_S` (30), não `MAX_TAKE_S`.
2. Música jogável exige também `lyrics.txt`, porque os trechos vêm dele.

## Review Focus

1. **Letra com contagem de tokens diferente das palavras alinhadas em job real** (pontuação solta como "—", adlibs). Esperado: a música sai da lista do setup com aviso nomeando as duas contagens, nunca trechos deslocados. Pinado em Task 1 (`test_contagem_divergente_e_erro`) e Task 6 (roteiro manual com job real).
2. **Take mais longo que o trecho por causa do pré-roll.** Esperado: o fim do trecho não é cortado. Pinado em Task 3 (`test_max_take_cobre_trecho_mais_pre_roll`).
3. **`start`/`end` adulterados no cliente** (negativos, invertidos, além da música, texto). Esperado: 400 antes de qualquer ffmpeg. Pinado em Task 3 (parametrizado).
4. **Job id com travessia de caminho nas rotas novas e nas do player.** Esperado: 400. Pinado em Tasks 2 e 4.
5. **Música selecionada cujos trechos falham ou vêm vazios.** Esperado: aviso e a música sai da partida; se nenhuma sobrar, "Começar" não inicia. Pinado em Task 6 (roteiro manual, item 3).

---

### Task 1: Trechos a partir da letra — `karaoke/trechos.py`

**Files:**
- Create: `karaoke/trechos.py`
- Test: `tests/test_trechos.py`

**Interfaces:**
- Produces:
  - `TRECHO_MIN_S: float = 20.0`, `TRECHO_MAX_S: float = 30.0`
  - `normaliza(texto: str) -> str`
  - `versos_da_letra(linhas: list[str], palavras: list[dict]) -> list[dict]`. Cada verso é `{"texto": str, "inicio": float, "fim": float, "estrofe": int, "palavras": [{"texto": str, "inicio": float, "fim": float}]}`. Levanta `ValueError` se `total de tokens != len(palavras)`.
  - `trechos(versos: list[dict]) -> list[dict]`. Cada trecho é `{"id": int, "inicio": float, "fim": float, "refrao": bool, "longo": bool, "versos": [verso, ...]}`, na ordem de seleção (prioridade desc, depois `inicio` asc), com `id` = posição nessa lista.
  - `trechos_da_letra(linhas: list[str], palavras: list[dict]) -> list[dict]`, que é `trechos(versos_da_letra(...))`.

- [ ] **Step 1: Write the failing tests**

Helper no topo do teste, que alinha cada token com duração fixa e sem pausa:

```python
def _alinha(linhas, dur=1.0):
    t, out = 0.0, []
    for linha in linhas:
        for tok in linha.split():
            out.append({"word": tok, "start": t, "end": t + dur, "score": 1.0})
            t += dur
    return out
```

Letras de teste (cada verso tem 6 palavras, ou seja, 6 s):
- `REFRAO`, com 3 estrofes separadas por `""` e 10 versos de 6 tokens (60 s):
  - estrofe 0: `"Amor, amor, meu amor que vai"`, `"Sempre volta sem pedir sua licenca"` e 4 versos únicos;
  - estrofe 1: `"amor amor meu amor que vai!"` e `"Sempre volta sem pedir sua licenca"` (o refrão repetido, com caixa e pontuação diferentes);
  - estrofe 2: 2 versos únicos.
- `SEM_REPETICAO`: 12 versos únicos de 6 palavras.

Testes e asserções:
- `test_versos_seguem_linhas_e_estrofes`: `len(versos) == linhas não vazias`; `versos[0]["inicio"] == 0.0`; `versos[0]["fim"] == 6.0`; o `estrofe` incrementa após cada linha em branco; `versos[0]["palavras"][0]["texto"] == "Amor,"`.
- `test_contagem_divergente_e_erro`: `pytest.raises(ValueError, match=r"\d+ tokens.*\d+ palavras")` quando `palavras` tem um item a menos.
- `test_normaliza_ignora_caixa_acento_pontuacao`: `normaliza("Amor, AMÔR!  meu") == normaliza("amor amor meu")`.
- `test_refrao_vem_primeiro`: `t = trechos_da_letra(REFRAO, _alinha(REFRAO))`; `t[0]["refrao"] is True`; os versos de `t[0]` incluem um verso cujo `normaliza(texto)` é o do refrão; todo trecho `refrao: True` aparece antes de qualquer `refrao: False`.
- `test_sem_repeticao_cai_na_reserva`: `t = trechos_da_letra(SEM_REPETICAO, ...)`; `t` não vazio; todos `refrao is False`; para todo trecho, `20.0 <= fim - inicio <= 30.0`; nenhum par de trechos se sobrepõe (`a.fim <= b.inicio or b.fim <= a.inicio`).
- `test_verso_longo_vira_trecho_marcado`: um verso de 40 tokens (`dur=1.0`, ou seja, 40 s) → existe trecho com `longo is True` e um verso só.
- `test_letra_curta_devolve_vazio`: 2 versos de 6 s → `trechos_da_letra(...) == []`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_trechos.py -v`
Expected: FAIL (`ModuleNotFoundError: karaoke.trechos`).

- [ ] **Step 3: Implement `karaoke/trechos.py`**

Lógica pura, sem I/O. `versos_da_letra` segue a regra do `karaoke/ass_builder.py:124` (`group_words_by_lyrics_lines`): tokens por `line.split()`, consumo sequencial, linha em branco incrementa `estrofe`. A mensagem do `ValueError` contém `"{n_tokens} tokens"` e `"{n_palavras} palavras"`. `normaliza`: `unicodedata.normalize("NFKD")`, remove combinantes, minúsculas, troca `[^\w\s]` por espaço, colapsa espaços.

`trechos` (algoritmo, que o teste não determina sozinho):
```text
repetido[i] = contagem de normaliza(verso.texto) na letra >= 2
para cada inicio i:
    j = maior indice com versos[j].fim - versos[i].inicio <= TRECHO_MAX_S
    se nenhum j (verso i sozinho > MAX): candidato [i..i], longo=True
    senao se versos[j].fim - versos[i].inicio >= TRECHO_MIN_S: candidato [i..j], longo=False
    (senao: sem candidato a partir de i)
prioridade = soma(fim-inicio dos versos repetidos do bloco) / (fim-inicio do bloco)
ordena candidatos por (-prioridade, inicio); guloso aceita quem nao sobrepoe aceitos
refrao = prioridade > 0; id = posicao na lista final
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_trechos.py -v`
Expected: PASS (7 testes).

- [ ] **Step 5: Commit**

```bash
git add karaoke/trechos.py tests/test_trechos.py
git commit -m "feat(trechos): trechos de 20-30 s da letra, refrao primeiro"
```

---

### Task 2: Rotas do jogo — lista, trechos e base

**Files:**
- Modify: `karaoke/paths.py` (novo acessor ao lado de `demucs_out_dir`, linha ~156)
- Modify: `scripts/09_video_rendering.py:528` (usar o acessor)
- Create: `server_karaoke_game_addendum.py`
- Modify: `server.py:29-44` (importar e registrar a rota, como `make_score_route`)
- Test: `tests/test_karaoke_game_route.py`

**Interfaces:**
- Consumes: `trechos_da_letra` (Task 1); `REF_ID_RE`, `_erro` de `server_score_addendum`; `state_store.get_job(job_id)` (devolve dict com `audio_name` ou `None`).
- Produces:
  - `kpaths.instrumental(job_id: str) -> Path` = `demucs_out_dir(job_id) / "no_vocals.wav"`
  - `JOBS_DIR` (módulo, `kpaths.repos_root() / "work" / "jobs"`, monkeypatchável nos testes)
  - `make_karaoke_game_route(app) -> None`, registrando:
    - `GET /api/karaoke/songs` → `[{"id", "titulo", "duracao_s"}]`, ordenada por `titulo`
    - `GET /api/karaoke/<job>/trechos` → saída de `trechos_da_letra`
    - `GET /api/karaoke/<job>/base` → `audio/wav`
  - `jogavel(job_id: str) -> bool`: existem `word_timing_json`, `vocals_raw`, `instrumental` e `lyrics_path`.

- [ ] **Step 1: Write the failing tests**

Fixture `jobs` que faz monkeypatch de `kpaths.repos_root` para `tmp_path` (todos os acessores derivam dele) e de `mod.JOBS_DIR`. Também troca `state_store.get_job` por um dict fake. Helper `_cria_job(id, sem=None)` grava os 4 arquivos (WAVs de 1 s via `soundfile`, letra de 6 versos × 6 tokens e `word_timing` via o mesmo `_alinha` da Task 1, copiado) e omite o nomeado em `sem`.

- `test_lista_so_jogaveis`: jobs `ok`, `sem_base` (sem instrumental), `sem_letra` (sem lyrics) → `[s["id"] for s in r.json] == ["ok"]`.
- `test_titulo_vem_do_audio_name_e_cai_no_id`: `get_job` devolve `{"audio_name": "Minha Musica.mp3"}` para `ok` → `titulo == "Minha Musica"`; para job sem estado → `titulo == id`.
- `test_trechos_devolve_lista`: 36 s cantados → `200`, lista com `inicio`, `fim`, `versos`.
- `test_trechos_letra_inconsistente_da_422`: `word_timing` com uma palavra a menos → `422` e `"tokens"` em `error`.
- `test_base_serve_wav`: `200`, `mimetype == "audio/wav"`.
- `test_job_inexistente_da_404` nas duas rotas com `<job>`.
- `@pytest.mark.parametrize("mau", ["..", "a.b", "x"*65])` `test_job_invalido_da_400` nas duas rotas com `<job>`. Use `"a.b"` e `".."`: barras não chegam como `<job>` no Flask.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_karaoke_game_route.py -v`
Expected: FAIL (`ModuleNotFoundError: server_karaoke_game_addendum`).

- [ ] **Step 3: Implement**

`kpaths.instrumental`, e troca do caminho em `09_video_rendering.py:528` por `kpaths.instrumental(job_id)`. Addendum: `duracao_s` via `soundfile.info(kpaths.instrumental(id)).duration`, arredondado a 1 casa. `titulo` = `Path(audio_name).stem` se houver estado, senão o id. A lista varre `JOBS_DIR.iterdir()`, filtra `REF_ID_RE` e `jogavel`. As rotas `<job>` respondem 400 (regex), depois 404 (`not jogavel`), depois o conteúdo. Lê a letra com `encoding="utf-8"` e `splitlines()`. Registrar em `server.py` ao lado de `make_score_route(app)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_karaoke_game_route.py tests/test_paths_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add karaoke/paths.py scripts/09_video_rendering.py server_karaoke_game_addendum.py server.py tests/test_karaoke_game_route.py
git commit -m "feat(karaoke-game): rotas de musicas jogaveis, trechos e base"
```

---

### Task 3: `/api/score` recortado por trecho

**Files:**
- Modify: `server_score_addendum.py` (`MAX_TAKE_S` linha ~24; corpo de `api_score` no ramo `mode == "karaoke"`, linhas ~126-170)
- Test: `tests/test_score_route.py`, `tests/test_scorer.py`

**Interfaces:**
- Consumes: `TRECHO_MAX_S` (Task 1); `track_from_word_timing(words, samples, sr)` (existente).
- Produces: `POST /api/score` aceita `start`/`end` (form, segundos) em `mode=karaoke`. Sem os dois, o comportamento atual não muda.

- [ ] **Step 1: Write the failing tests**

Em `tests/test_scorer.py`:
- `test_karaoke_trecho_certo_supera_trecho_errado`: áudio = `bursts(TIMES, FREQS)` seguido de `bursts(TIMES, DIFERENTE_FREQS_5)` deslocado +5 s (`DIFERENTE_FREQS_5 = [392.0, 349.0, 440.0, 330.0, 494.0]`). `words_a` com as palavras de 0–3,5 s, `words_b` com as de 5–8,5 s. `take = track_from_audio(bursts(TIMES, FREQS), SR)`. Asserção: `score(track_from_word_timing(words_a, audio, SR), take).melody >= 85` e `score(track_from_word_timing(words_b, audio, SR), take).melody <= 30`.

Em `tests/test_score_route.py` (fixture nova `job_karaoke` com monkeypatch de `kpaths.repos_root` e um job com `word_timing.json` + `vocals_raw.wav` de 10 s):
- `test_max_take_cobre_trecho_mais_pre_roll`: `mod.MAX_TAKE_S >= TRECHO_MAX_S + 2`.
- `@pytest.mark.parametrize("start,end", [("-1","5"), ("5","5"), ("6","2"), ("0","31"), ("0","99"), ("a","5"), ("5", "")])` `test_trecho_invalido_da_400`. Só `start` sem `end` também é 400. A asserção inclui que o ffmpeg não foi chamado (monkeypatch de `_webm_para_wav` registrando chamada).
- `test_trecho_sem_palavras_da_422`: `start=9.0,end=9.9` num job sem palavras nessa janela → 422.
- `test_trecho_valido_pontua`: `start=0,end=4` → 200 com `total` numérico.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_score_route.py tests/test_scorer.py -k "trecho or max_take" -v`
Expected: FAIL. O teste do scorer pode já passar, porque usa só funções existentes. Se passar, ele fica como guarda e não bloqueia.

- [ ] **Step 3: Implement**

- `MAX_TAKE_S = 35`, com comentário: `# ponytail: >= TRECHO_MAX_S + PRE_ROLL_S do navegador (2 s); subir junto se o pre-roll crescer`.
- Parse de `start`/`end` **antes** do ffmpeg, só em `mode == "karaoke"`. Ambos ausentes → fluxo atual. Um só, não numérico, `start < 0`, `end <= start` ou `end - start > TRECHO_MAX_S` → `_erro(..., 400)` com a palavra `trecho` na mensagem.
- `end` acima da duração (`soundfile.info(vocals).duration`) → 400.
- Com trecho: `words = [w for w in words if start <= w["start"] and w["end"] <= end]`. Lista vazia → `_erro("trecho sem palavras alinhadas", 422)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_score_route.py tests/test_scorer.py -v`
Expected: PASS (inclusive os testes antigos).

- [ ] **Step 5: Commit**

```bash
git add server_score_addendum.py tests/test_score_route.py tests/test_scorer.py
git commit -m "feat(score): karaoke pontua so o trecho [start, end]"
```

---

### Task 4: Rotas do player apontando para os caminhos certos

**Files:**
- Create: `server_result_addendum.py`
- Modify: `server.py:~488-540` (remover `/api/result/ass`, `/lyrics`, `/audio` e `/word_timing` e registrar o addendum)
- Test: `tests/test_result_route.py`

**Interfaces:**
- Consumes: `REF_ID_RE`, `_erro`; `kpaths.final_ass`, `kpaths.lyrics_path`, `kpaths.input_dir`, `kpaths.word_timing_json`.
- Produces: `make_result_route(app) -> None` com as mesmas URLs e o mesmo query param `job_id` de hoje (o `karaoke-player.js:374-404` não muda).

- [ ] **Step 1: Write the failing tests**

Com o mesmo monkeypatch de `kpaths.repos_root`:
- `test_audio_acha_song_no_input_do_job`: `work/jobs/j1/input/song.wav` → `/api/result/audio?job_id=j1` 200 `audio/wav`.
- `test_ass_le_08_ass_lyrics`: `kpaths.final_ass("j1")` existe → 200 e o corpo igual ao arquivo.
- `test_lyrics_e_word_timing_do_job`: 200 nas duas rotas.
- `test_job_id_ausente_da_400` e `@pytest.mark.parametrize("mau", ["../x", "a/b", "x"*65])` `test_job_id_invalido_da_400` nas quatro rotas.
- `test_arquivo_ausente_da_404` nas quatro rotas.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_result_route.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

Mover as quatro rotas para o addendum. O áudio procura `song{ext}` em `kpaths.input_dir(job)` para as mesmas extensões e MIME de hoje. O `.ass` usa `kpaths.final_ass(job)` e mantém o `download_name="karaoke.ass"`. Validar `job_id` pela `REF_ID_RE` antes de montar caminho.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_result_route.py -v` e depois a suíte inteira: `.venv/Scripts/python -m pytest tests -q --ignore=tests/integration --ignore=tests/smoke`
Expected: PASS, sem regressão.

- [ ] **Step 5: Commit**

```bash
git add server_result_addendum.py server.py tests/test_result_route.py
git commit -m "fix(result): rotas do player leem work/jobs e validam job_id"
```

---

### Task 5: Componente de letra do trecho — `web/letra-trecho.js`

**Files:**
- Create: `web/letra-trecho.js`
- Modify: `web/party.html` (CSS do componente, no bloco `<style>` junto aos estilos da seção `#round`)

**Interfaces:**
- Consumes: trecho da Task 2 (`versos[].palavras[]` com `texto`, `inicio`, `fim` em segundos **absolutos da música**).
- Produces: `criaLetraTrecho(container: HTMLElement, versos: Array, audio: HTMLAudioElement) -> { para(): void }`, global como `criaMedidor`/`criaPlayer`.

- [ ] **Step 1: Implement**

Monta um `.verso` por verso e um `<span class="palavra" data-p>` por palavra, com camada de preenchimento por `--fill` (0–1). Um laço `requestAnimationFrame` lê `audio.currentTime` e faz duas coisas:
- marca o verso `passado` (`t >= fim`), `ativo` (`inicio <= t < fim`) ou `futuro`;
- define `--fill = clamp((t − inicio) / (fim − inicio), 0, 1)` por palavra.

É a mesma regra do `karaoke-player.js:192-226`. O verso ativo rola para o centro do container com `scrollIntoView({block: "center", behavior: "smooth"})`, só na troca de verso. `para()` cancela o laço e limpa o container. Texto inserido com `textContent`, nunca `innerHTML`.

- [ ] **Step 2: Verify manually**

Servidor de pé (`.claude/launch.json` da raiz, porta 5077). No console do `party.html`, crie um `<audio>` apontando para `/api/karaoke/<job>/base` com `currentTime = trecho.inicio`, chame `criaLetraTrecho` com os versos de `/api/karaoke/<job>/trechos` e dê play.
Expected: palavras preenchem em sincronia com a base, o verso ativo destaca, e `para()` remove tudo e para o laço (sem erro no console).

- [ ] **Step 3: Commit**

```bash
git add web/letra-trecho.js web/party.html
git commit -m "feat(party): componente de letra do trecho"
```

---

### Task 6: Modo Karaokê no `party.html`

**Files:**
- Create: `web/karaoke-vez.js`
- Modify: `web/party.html` (setup em `#setup` ~linhas 236-268; `$("comecar")` ~441; `proximaRodada`/`proximoJogadorDaRodada` ~487-507; `rec.onstop` ~525-575)

**Interfaces:**
- Consumes: rotas da Task 2, `start`/`end` da Task 3, `criaLetraTrecho` (Task 5), `criaMedidor` (existente).
- Produces (em `web/karaoke-vez.js`, globais):
  - `montaFilaDeTrechos(porMusica: Array<{musica: {id, titulo}, trechos: Array}>) -> Array<{job, titulo, inicio, fim, versos}>`: descarta `longo`, e intercala as músicas (um de cada por vez, na ordem que cada lista já traz, ou seja, refrão primeiro).
  - `vezKaraoke({trecho, audio, letraEl, medidorEl, estadoEl, stream, aoTerminar: (blob) => void}) -> { cancela(): void }`: contagem 3‑2‑1 em `estadoEl`, `audio.src = /api/karaoke/<job>/base`, `currentTime = max(0, inicio − PRE_ROLL_S)`, `play()` e `MediaRecorder.start()` juntos. Ao `currentTime >= fim`: pausa a base, `rec.stop()`, e `aoTerminar(blob)`.

Decisões de integração no `party.html`:
- Setup:
  - rádio `modo` (Imitar som | Karaokê) acima de "Rodadas";
  - no Karaokê, mostra `#lista-musicas` (checkboxes vindos de `/api/karaoke/songs`) e o link `<a href="/static/index.html" target="_blank">Adicionar música</a>`;
  - lista vazia mostra "Nenhuma música processada ainda" junto ao link;
  - trocar o modo ajusta `#dificuldade` para `oitava` (Karaokê) ou `relativo` (Imitar), sem travar a escolha do usuário depois.
- `comecar` no Karaokê:
  - busca `/api/karaoke/<id>/trechos` de cada música marcada;
  - música com erro ou lista vazia sai da partida com aviso em `#estado-setup` (`"<titulo>: <erro>"`);
  - se nenhuma sobrar, não inicia;
  - `baseClipes = montaFilaDeTrechos(...)`. A fila **não** é embaralhada, a ordem é a da função. Ao esgotar, recomeça do início, com o mesmo `alert` de repetição do Imitar.
- Rodada no Karaokê:
  - `#clip-titulo` mostra o título da música;
  - o player da referência (`.reproduzir`) fica oculto;
  - um `#letra-trecho` fica visível;
  - `#rec` vira o botão "Cantar": um clique só e a parada é automática (sem segundo clique).
- `rec.onstop` e o envio: a montagem do `FormData` passa a vir de uma função `camposDoScore()`. Imitar manda `mode=mimic, ref=clipe.id`. Karaokê manda `mode=karaoke, ref=trecho.job, start=trecho.inicio, end=trecho.fim`. As duas mandam `pitch`. O resto do fluxo (pontos, `takesDaRodada`, audição) não muda.
- Erro de score no Karaokê: mostra a mensagem e reabilita "Cantar" para regravar, igual ao Imitar.

- [ ] **Step 1: Implement `web/karaoke-vez.js`** com as duas funções acima. `PRE_ROLL_S = 2` e `CONTAGEM_S = 3` como constantes no topo.

- [ ] **Step 2: Integrar no `party.html`** conforme as decisões acima, carregando `letra-trecho.js` e `karaoke-vez.js` junto aos outros `<script>`.

- [ ] **Step 3: Verificação manual (roteiro)**

Com o servidor na porta 5077:
1. Nenhum job processado → modo Karaokê mostra "Nenhuma música processada ainda" e o link abre `index.html` em nova aba.
2. Com um job real processado (rodar o pipeline numa música curta antes): a música aparece com título e duração.
3. Renomeie temporariamente o `lyrics.txt` de um segundo job para provocar falha → ele some da lista. Com uma letra inconsistente, o aviso no setup nomeia as contagens. Com só ele marcado, "Começar" não inicia.
4. Partida com 2 jogadores e 2 rodadas: contagem 3‑2‑1; a base entra 2 s antes do primeiro verso; a letra acende em sincronia; a gravação para sozinha no fim do trecho; a audição toca os dois takes; o placar soma.
5. DevTools → Network: o POST `/api/score` leva `mode=karaoke`, `ref`, `start`, `end` e `pitch=oitava` (padrão do Karaokê). Troque para Difícil e confira `pitch=estrito`.
6. Volte ao modo Imitar e jogue uma rodada: comportamento igual ao de antes, com `pitch=relativo`.
7. Celular (375 px): setup e rodada sem rolagem lateral.

- [ ] **Step 4: Commit**

```bash
git add web/karaoke-vez.js web/party.html
git commit -m "feat(party): modo Karaoke com rodadas por trecho"
```
