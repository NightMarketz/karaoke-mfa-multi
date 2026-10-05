# Jogo de karaokê com qualquer música — desenho

Data: 2026-10-05. Base: commit `58b83cb` (scorer com melodia por frame no mesmo
instante e níveis de afinação `relativo | oitava | estrito`). O seletor de
dificuldade do `party.html` existe no disco, junto com o redesenho ainda sem
commit.

## Objetivo

Cantar no jogo de festa qualquer música que já passou pelo pipeline, com a base
tocando, a letra acendendo e uma nota justa no fim. "Qualquer música" significa
qualquer job processado: o pipeline já produz tudo que o jogo precisa (base sem
voz, voz isolada, tempo de cada palavra). O que falta é a tela que junta isso e
um scorer que compare um **trecho**, não a música inteira.

## Decisões (todas do usuário, 2026-10-05)

| Tema | Decisão | Primeira entrega |
|---|---|---|
| Formato | Rodadas por trecho **e** modo solo com a música inteira | rodadas por trecho |
| Escolha do trecho | Automática, priorizando o refrão; versos comuns como reserva | idem |
| O que toca | Configurável: só base, ou base + voz-guia | só base |
| Origem das músicas | Lista das processadas + link "Adicionar música" para o `index.html` | idem |
| O que se vê | Configurável: letra + medidor, ou + linha de afinação ao vivo | letra + medidor |
| Arquitetura | Estender o `party.html` com o modo Karaokê (abordagem 1 de 3) | idem |

Abordagens descartadas: página nova `karaoke-game.html` (duplicaria rodadas,
votação e placar) e escolha de trechos no navegador (tiraria a regra do refrão
dos testes em Python).

## Etapa 1 — rodadas por trecho

### 1. Trechos — `karaoke/trechos.py` (lógica pura, sem I/O)

**Entrada:** linhas do `lyrics.txt` (`kpaths.lyrics_path`) e a lista
`[{word, start, end, score}]` do `word_timing.json` (`kpaths.word_timing_json`).

**Versos.** Cada linha não vazia da letra vira um verso, consumindo palavras do
`word_timing` em sequência, uma por token de `line.split()`. É a mesma regra do
`group_words_by_lyrics_lines` (`karaoke/ass_builder.py:124`). Linhas em branco
separam estrofes: cada verso guarda o índice da sua estrofe. Um verso tem
`{texto, inicio, fim, estrofe, palavras: [{texto, inicio, fim}]}`, com
`inicio`/`fim` vindos da primeira/última palavra.

Se o total de tokens da letra for diferente do total de palavras alinhadas, a
função levanta `ValueError` com as duas contagens. Isso não vira trecho
desalinhado.

**Candidatos.** Blocos de versos consecutivos com duração (`fim` do último −
`inicio` do primeiro) entre `TRECHO_MIN_S = 20` e `TRECHO_MAX_S = 30`. O bloco
nunca corta verso, e pode atravessar estrofes. Um verso sozinho com mais de
`TRECHO_MAX_S` vira um candidato de um verso só, marcado `longo: true`. A rota de
score recusa takes acima de 30 s, então o jogo pula esses candidatos. Versos que
não fecham 20 s com os vizinhos (por exemplo, a cauda da música) ficam sem
trecho. Uma letra com menos de 20 s cantados no total devolve lista vazia, que o
jogo trata como música sem trechos (seção 4).

**Refrão.** Normalização do texto do verso: minúsculas, sem acento
(`unicodedata` NFKD), sem pontuação, espaços colapsados. Um verso é *repetido*
quando o texto normalizado aparece 2+ vezes na letra. A prioridade de um
candidato é a fração da sua duração coberta por versos repetidos.

**Seleção.** Os candidatos são ordenados por prioridade (desc) e depois por
`inicio` (asc). Um guloso aceita cada candidato que não se sobrepõe a um já
aceito. Saída: lista ordenada de
`{id, inicio, fim, refrao: bool, versos: [...]}`, com `refrao = prioridade > 0`.
Uma letra sem repetição sai inteira com `refrao: false`: é a reserva por versos,
sem caminho separado.

**Testes** (`tests/test_trechos.py`):
- letra com refrão repetido → os primeiros trechos são `refrao: true` e cobrem os versos repetidos;
- letra sem repetição → todos `refrao: false`, sem sobreposição e com duração dentro de [20, 30];
- verso único > 30 s → `longo: true`;
- letra com menos de 20 s cantados → lista vazia;
- contagem de tokens ≠ palavras → `ValueError` com os dois números;
- normalização: "Amor!" e "amor" contam como repetição.

### 2. Servidor — `server_karaoke_game_addendum.py`

Mesmo molde de `server_score_addendum.py` (`make_*_route(app)` chamado pelo
`server.py`). Todo `job` é validado pela `REF_ID_RE` antes de virar caminho.

| Rota | Faz |
|---|---|
| `GET /api/karaoke/songs` | Lista jobs jogáveis: têm `word_timing.json`, `vocals_raw.wav` **e** `no_vocals.wav`. Devolve `{id, titulo, duracao_s}`, com título do nome do arquivo de entrada. Jobs incompletos não aparecem. |
| `GET /api/karaoke/<job>/trechos` | Saída da seção 1. Letra inconsistente → 422 com a mensagem do `ValueError`. |
| `GET /api/karaoke/<job>/base` | Serve o `no_vocals.wav`. |

Novo acessor `kpaths.instrumental(job)` →
`demucs_out_dir(job) / "no_vocals.wav"`. O `scripts/09_video_rendering.py:528`
passa a usá-lo no lugar do caminho montado à mão.

**`/api/score` no modo karaokê** ganha `start` e `end` opcionais (segundos).
Quando vêm:
- validação: números, `0 ≤ start < end`, `end − start ≤ MAX_TAKE_S`, `end` dentro da duração da voz isolada. Senão, 400;
- referência: `track_from_word_timing` só com as palavras em que `start ≤ palavra.start` e `palavra.end ≤ end`. Nenhuma palavra → 422.

Sem `start`/`end`, o comportamento atual não muda. O nível de afinação continua
vindo de `pitch`, com padrão `oitava` no karaokê.

**Conserto das rotas do player** (tarefa própria): `/api/result/audio`
(`server.py:508`) lê `input/jobs/<id>/song*`, mas o upload grava em
`work/jobs/<id>/input/`. `/api/result/ass` (`server.py:491`) lê
`06_ass/karaoke.ass`, mas o pipeline escreve `08_ass/lyrics.ass`. As duas passam
a usar os acessores de `kpaths` e a validar o `job_id` pela `REF_ID_RE`.

**Testes** (`tests/test_karaoke_game_route.py`):
- lista ignora job sem algum dos três arquivos;
- regex barra travessia em todas as rotas;
- base servida com o tipo certo;
- `start`/`end` inválidos → 400;
- trecho sem palavras → 422.

Em `tests/test_scorer.py`, uma fixture com dois trechos de melodias diferentes
na mesma "música": o take que canta o trecho A pontua alto contra A e baixo
contra B.

### 3. Navegador

**Setup do `party.html`:**
- escolha de modo **Imitar som | Karaokê**;
- no modo Karaokê, lista de músicas (multisseleção) vinda de `/api/karaoke/songs` e link "Adicionar música" que abre `/static/index.html` em nova aba;
- lista vazia → "Nenhuma música processada ainda" + o link;
- seletor de dificuldade com padrão **Normal (oitava)** no Karaokê e **Fácil (relativo)** no Imitar.

**Sorteio:** ao começar, o jogo busca os trechos de cada música escolhida. A
cada rodada tira o próximo trecho não usado, alternando músicas e começando
pelos de refrão. Candidatos `longo` são pulados. Quando acabam os trechos, os
mesmos podem repetir, com o mesmo aviso que o modo Imitar já dá.

**Vez do jogador (Karaokê):**
1. Tela mostra a música e os versos do trecho.
2. "Cantar" → contagem de 3 s → a base toca a partir de `inicio − PRE_ROLL_S` (`PRE_ROLL_S = 2`) e o `MediaRecorder` começa junto.
3. A letra acende palavra por palavra pelo `currentTime` da base, com o medidor de microfone visível.
4. Em `currentTime ≥ fim`, base e gravação param e o take vai para `/api/score` com `mode=karaoke`, `ref=<job>`, `start=inicio`, `end=fim`, `pitch`.

O pré-roll não precisa de compensação: `track_from_audio` recorta o silêncio
inicial e `score()` estima o deslocamento entre take e referência pelos ataques.

**`web/letra-trecho.js`** (componente novo): `criaLetraTrecho(container, versos,
audio)`. Ele monta os versos, e num laço de `requestAnimationFrame` marca cada
verso como `passado | ativo | futuro` e preenche a largura de cada palavra por
`(currentTime − inicio) / (fim − inicio)`. É a mesma lógica do
`karaoke-player.js:192-226`, que não é reaproveitável porque é um singleton preso
ao DOM do `index.html` (`window.karaokePlayer`). `para()` cancela o laço.

**Audição, votação e placar:** sem mudança. As gravações são reouvidas sem a
base.

**Verificação manual** (não há suíte de interface): roteiro no plano cobrindo
lista vazia, uma partida com 2 jogadores, o trecho tocando e acendendo
sincronizado, a parada automática no fim e a troca de dificuldade aparecendo no
`pitch` da requisição.

### 4. Erros

- Microfone negado → mesma mensagem e fluxo do modo Imitar.
- `/api/karaoke/<job>/trechos` falhou ou veio vazio → a música sai da partida com aviso no setup. Se nenhuma sobrar, "Começar" não inicia.
- Score com erro (400/422/5xx) → a vez mostra a mensagem do servidor e permite regravar, como no Imitar.

## Etapas seguintes (escopo registrado, sem desenho de implementação)

**Etapa 2 — voz-guia opcional.** Antes da opção existir, um teste de vazamento:
base + voz original tocando na caixa, microfone gravando e jogador calado. Ele
mede quanto a nota sobe. O limite aceitável é definido nessa etapa, com o número
medido. A opção só entra no setup se o ganho ficar abaixo do limite. Conecta com
o P1 do roadmap de 2026-09-20.

**Etapa 3 — linha de afinação ao vivo.** Detector de altura em JS (o plano
2026-09-21 §2 cita portar o NSDF do `karaoke-voice-game`, e o YIN do Encore
Karaoke é alternativa de ~65 linhas). Contorno da referência servido como JSON
na grade de 10 ms. É só visual: a nota continua sendo a do servidor.

**Etapa 4 — modo solo com a música inteira.** Exige:
- subir `MAX_TAKE_S` e `MAX_UPLOAD_BYTES` no modo solo;
- trocar a correlação cruzada por FFT acima de ~2 min (`scorer.py:182-184` já mede 2,1 s a 240 s);
- nota por verso, reusando os versos da seção 1.

## Fora de escopo

- Modo rápido de processamento só para o jogo (pular ilustração e render). É item separado, se for pedido.
- Upload de música dentro do jogo: o atalho leva ao `index.html`.
- Detecção de refrão por áudio: a repetição na letra basta para a etapa 1.
