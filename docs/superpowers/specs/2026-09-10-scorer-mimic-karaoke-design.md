# Scorer de imitação e canto — um scorer, dois modos

Data: 2026-09-10
Branch: `claude/mimic-party-discord-logic-4b5f14`

## Objetivo

Pontuar a gravação de um jogador contra uma referência, em duas modalidades que
compartilham **o mesmo scorer**:

- **mimic** — referência é um clipe de som cru (animal, máquina, voz). Sem letra.
- **karaoke** — referência é um trecho de música cujo tempo por palavra o pipeline deste
  repo já produz (`word_timing.json`).

Marco A (este spec): **um jogador, uma rodada, uma página local**. Toca a referência,
grava o microfone, devolve três sub-notas e uma nota final. Sem lobby, sem rodadas, sem
roda de sabotagem, sem Discord. O risco do projeto está no scorer; lobby é tarde de
trabalho.

## O que o jogo de referência mede (fonte, não memória)

O Mimic Party pontua **melodia** (contorno de pitch), **ritmo** (timing) e **ataques**
(número de sons distintos), e **ignora timbre de propósito** — é o que permite criança e
adulto tirarem 100 no mesmo som. Todos gravam no mesmo countdown, sem ensaio.

Fontes: `store.steampowered.com/app/5053820`,
`mimicparty.wiki/en/guide/mimic-party-how-to-play`.

## Estado atual (medido, não lido)

Captura de microfone e extração de pitch **não existem** no repo. Busca por
`getUserMedia|MediaRecorder|AudioContext|pitch|f0` em `*.py`/`*.js`/`*.html` (excluindo
`obsolete/`) retorna 4 ocorrências em 3 arquivos, todas falso-positivo (`f0` como nome de variável
de frame em `scripts/compare_timing.py:6` e `:8`, `'pitch'` como chave de dict em
`scripts/fuse_sofa_rosvot.py:99`, e prosa de comentário em `karaoke/background.py:80`). O player em `web/karaoke-player.js` só toca áudio e
preenche palavra.

O que existe e será reusado:

| peça | onde | vira o quê |
|---|---|---|
| detector de onset (RMS + derivada + gap mínimo) | `scripts/08_onset_dtw.py:46` | **ataques** e **ritmo** |
| VAD por energia com limiar adaptativo | `karaoke/vad.py:67` | recorte do take, descarte de silêncio |
| padrão de limiares com relatório | `karaoke/qc.py` | régua de nota |
| gabarito por palavra | `work/jobs/<id>/05_alignment/word_timing.json` | referência do modo karaoke |
| ffmpeg 8.1 | PATH | decodifica o WebM do navegador para WAV 16k mono |

### Qualidade do gabarito do modo karaoke (medido em 2026-09-10)

Job `mimic_gab_01` (60s, 71 palavras, inglês). Coincidência do início de cada palavra com
onset vocal detectado (163 onsets, um a cada 0,296s), contra baseline de 2.000 sorteios
aleatórios de 71 inícios uniformes em [11,7s, 60,0s]:

| tolerância | acaso | MFA | whisperx |
|---|---|---|---|
| 0,05s | 23,4/71 (33%) | 32/71 (45%) p=0,027 | 25/71 (35%) p=0,383 |
| 0,10s | 33,0/71 (47%) | 47/71 (66%) p=0,001 | 39/71 (55%) p=0,098 |
| 0,20s | 38,4/71 (54%) | 56/71 (79%) p=0,000 | 43/71 (61%) p=0,157 |

Consequências que este spec **assume como dadas**:

1. O gabarito utilizável é o do **MFA**. O do whisperx é indistinguível do acaso nas três
   tolerâncias e não entra como referência.
2. A precisão do gabarito é de ordem **200ms, não de sílaba**. O modo karaoke pontua com
   tolerância derivada do intervalo mediano da referência (ver `RHYTHM_TOL_RATIO`) e **não**
   promete acerto sílaba a sílaba.
3. Nenhum ouvido humano validou o gabarito. Enquanto isso não acontecer, o modo karaoke é
   "melhor que acaso", não "correto".

## Recursos já instalados (reusar, não instalar)

Env `karaoke_env` (`C:\Users\Katz\miniforge3\envs\karaoke_env`) tem tudo:

| pacote | versão | uso |
|---|---|---|
| flask | 3.1.3 | rota do scorer |
| numpy | 1.26.4 | features |
| scipy | 1.17.1 | filtro e correlação |
| librosa | 0.11.0 | `librosa.pyin` → f0 com flag de *voiced* |
| soundfile | 0.13.1 | leitura de WAV |

**Nenhuma dependência nova.** Em particular, f0 **não** será escrito à mão: `librosa.pyin`
já está instalado e devolve `(f0, voiced_flag, voiced_prob)`.

## Arquitetura

A ideia que torna isto um scorer e não dois: **os dois modos produzem a mesma estrutura
intermediária**, e o scorer só compara duas dessas.

```
      modo mimic                         modo karaoke
   clipe .wav de referência        vocals_raw.wav + word_timing.json
            │                                   │
            └──────────────┬────────────────────┘
                           ▼
                     ReferenceTrack
            { onsets, f0_semitones, frame_dur, duration }
                           ▲
                           │  mesma função de extração
                take do jogador (WAV 16k mono)
                           │
                           ▼
            score(ref, take) -> ScoreReport
```

### Decisão de projeto: estrutura relativa, não sincronia absoluta

O scorer compara **forma**, não alinhamento absoluto:

- **melodia** usa semitons centrados na mediana do próprio take → imune a registro
  (criança e adulto empatam, que é a propriedade explícita do jogo de referência);
- **ritmo** compara intervalos *entre* ataques consecutivos, não instantes absolutos;
- **ataques** compara contagem.

Isso resolve de graça um problema que não sei medir: a **latência de captura do
navegador**, que varia por dispositivo. Pontuando estrutura relativa, um atraso global
constante não altera nota nenhuma. Não há calibração de latência a fazer no marco A
porque nada no scorer depende dela.

### Componente 1 — `karaoke/scorer.py` (novo)

Lógica pura, sem I/O e sem subprocess, no molde de `karaoke/qc.py`.

```python
@dataclass
class ReferenceTrack:
    onsets: np.ndarray           # instantes de ataque, em segundos
    semitones: np.ndarray        # contorno centrado na mediana, so frames voiced
    frame_dur: float
    duration: float
    n_voiced: int                # denominador do contorno
    n_frames: int                # total de frames analisados
    n_octave_suspect: int        # |semitom| > 11: erro de oitava do pyin, contado nao corrigido

@dataclass
class ScoreReport:
    melody: float            # 0..100
    rhythm: float            # 0..100
    attacks: float           # 0..100
    total: float             # 0..100
    n_onsets_ref: int
    n_onsets_take: int
    n_frames_compared: int   # cardinalidade: zero é falha, não sucesso
    rhythm_tol_s: float      # tolerância efetivamente usada, para auditoria

def track_from_audio(samples, sr) -> ReferenceTrack
def track_from_word_timing(words, samples, sr) -> ReferenceTrack
def score(ref: ReferenceTrack, take: ReferenceTrack) -> ScoreReport
```

Pesos e tolerâncias como constantes de módulo nomeadas — são knobs de calibração, não
valores sagrados:

```python
# Tolerancia de ritmo e RELATIVA ao intervalo mediano da referencia, com piso absoluto.
# Motivo medido em 2026-09-10: no modo karaoke o intervalo mediano entre palavras e
# 0,140s — uma tolerancia absoluta de 200ms seria MAIOR que o proprio intervalo medido,
# e a nota de ritmo ficaria vazia (tudo dentro da tolerancia). Relativa da 0,049s -> piso
# 0,050s ali, e 0,210s no material sintetico de teste (intervalos de 0,6s), preservando
# os controles.
RHYTHM_TOL_RATIO = 0.35
RHYTHM_TOL_FLOOR_S = 0.050
WEIGHTS = {"melody": 0.45, "rhythm": 0.35, "attacks": 0.20}
```

`ScoreReport` carrega `n_frames_compared` e as duas contagens de onset porque **nota sem
denominador é opinião com número**: quem consome o relatório vê sobre quantos itens a
conta foi feita.

### Componente 2 — rota Flask (adendo, no molde de `server_preview_addendum.py`)

`POST /api/score`, `multipart/form-data`:

- `take` — áudio gravado pelo navegador (WebM/Opus)
- `mode` — `mimic` | `karaoke`
- `ref` — id do clipe (mimic) ou `job_id` (karaoke)

Fluxo: salva o upload num temporário → `ffmpeg -i take.webm -ar 16000 -ac 1 take.wav`
(mesmo padrão de `scripts/03_vocal_cleaning.py`, **incluindo o `mkdir` do diretório de
saída**, que foi bug real lá) → extrai as duas `ReferenceTrack` → devolve `ScoreReport` em
JSON.

Validação na fronteira de confiança (isto não encolhe): tamanho máximo do upload, `mode`
em lista fechada, `ref` resolvido contra o que existe em disco e **nunca interpolado em
caminho**. Upload que falha decodificação devolve 400 com motivo, não 500.

### Componente 3 — `web/mimic.html` (novo, uma página)

Sem build e sem framework, servida pelo `static_folder="web"` que `server.py:40` já
configura. `MediaRecorder` para gravar, `<audio>` para tocar a referência, um botão, e as
três sub-notas com a nota final.

Acessibilidade básica não é opcional: o disparo é um `<button>` com rótulo textual, o
estado de gravação é anunciado via `aria-live`, e nenhuma informação depende só de cor.

### Componente 4 — uma deleção no pipeline (exceção decidida em 2026-09-11)

`scripts/08_onset_dtw.py` perde `compute_rms`, `detect_onsets` e cinco constantes, que
passam a viver em `karaoke/onset.py`; o script importa de lá. É a única alteração de
pipeline no marco A, e existe para não duplicar ~25 linhas de lógica. Cerca: o detector
colapsado acha os mesmos 163 onsets no `vocals_raw.wav` de 60s que o original achou.

## Teste — `tests/test_scorer.py`

Cinco controles, todos sem microfone e sem humano, usando a referência contra
transformações dela mesma. **O controle negativo não é etapa opcional depois do teste: é
o teste.**

| # | Entrada | Esperado | Prova o quê |
|---|---|---|---|
| 1 | referência × ela mesma | total ≥ 95 | reconhece identidade |
| 2 | referência × clipe diferente | total abaixo do p95 do baseline aleatório | discrimina |
| 3 | referência × ela mesma **embaralhada no tempo** | ritmo e ataques baixos | não mede só timbre/espectro |
| 4 | referência × ela mesma **transposta** (±5 semitons) | melodia ainda ≥ 85 | é agnóstico a registro |
| 5 | **baseline aleatório**: N takes sintéticos | publica média e p95 | nenhuma nota é "boa" sem régua |

Os limiares numéricos da tabela (95, 85) são **alvos de calibração, não veredito sobre o
scorer**. Na primeira execução eles se tornam a medição: se identidade der 92, o número
que vira limiar é 92 e o teste passa a proteger esse patamar contra regressão. O que
**não** é negociável são estas tres relacoes, medidas em prototipo em 2026-09-10:

- `identidade ~= transposto` (a centragem na mediana torna transposicao gratuita: ambos 100,0)
- `identidade > embaralhado > clipe diferente` (100,0 > 35,6 > 12,0)
- `identidade > p95(acaso)` (100,0 > 49,5) — **este** e o requisito de discriminacao

Cuidado com um erro que a primeira versao deste spec cometeu: acaso e uma *distribuicao*,
nao um piso. O p95 dela e o limiar que a nota BOA precisa superar; nota ruim ficar abaixo
dele (clipe diferente deu 12,0 contra p95 49,5) e o comportamento correto. Exigir
`clipe diferente > acaso` e incoerente e foi removido.

Regras que os testes obedecem, escritas porque falhei nelas nesta mesma sessão:

- **Denominador junto do número.** Toda asserção sobre contagem afirma o total também.
- **Cardinalidade antes do veredito.** `n_frames_compared == 0` é **falha**, não sucesso.
  Cheque sobre conjunto vazio é verde universal.
- **Teste permissivo não vale como prova.** Nesta sessão o VAD aprovou 100% de dois
  alinhamentos que discordavam 5,94s entre si, porque marcava 49s de voz em 60s. Se um
  controle não fica vermelho quando eu sabotar o alvo, ele sai do spec.

## Fora de escopo (marco A)

Lobby, rodadas, ranking, roda de sabotagem, playback dos takes dos outros, multiplayer,
websocket, Discord Embedded App SDK, URL Mappings, packs de som, persistência de
resultado. Nada disso é difícil; nada disso prova o scorer.

Também fora: melhorar a precisão do gabarito além dos 200ms medidos, e reescrever
`scripts/03_forced_align.py` contra a API real do `ctc_forced_aligner 0.3.0` (divergente
em 6 pontos).

## Curadoria de referências mimic (medido em 2026-09-11)

Dez clipes do MyInstants em `input/mimic_refs/` (gitignored; `scripts/fetch_mimic_refs.py`
refaz). Pela rota real, identidade deu 100,0 nos dois pares testados e três dos quatro pares
"diferentes" deram 22,3 / 14,5 / 10,2 — bem abaixo do p95 do acaso (52,8). O quarto,
`bruh` × `screaming_goat`, deu **53,1**: `bruh` tem 0,8 s e 4 ataques, logo 3 intervalos de
ritmo, e a tolerância a onset de borda tem folga demais para tão pouco (ritmo 86,7 entre um
"bruh" e um berro de cabra).

**Regra:** referência com menos de 6 ataques ou menos de 1,5 s faz ritmo e ataques virarem
ruído. O script marca esses como FRÁGIL em vez de recusar — decisão de quem monta o pack.
Dos 10: 7 ok, 3 frágeis (`bruh`, `wow`, `ara_ara`), 0 reprovados. Dois candidatos originais
foram trocados por darem 0/26 e 4/26 frames voiced (fala de 0,8 s): **o limiar
`MIN_VOICED_FRAMES` não é afrouxado para acomodar clipe — troca-se o clipe.**

## Riscos

1. **O gabarito do karaoke tem erro de ~200ms e ninguém o ouviu.** A nota do modo karaoke
   herda esse erro inteiro. Mitigação: o modo mimic não depende de gabarito nenhum, então
   valida o scorer de forma independente; se o mimic pontua bem e o karaoke não, o problema
   é o gabarito, não o scorer.
2. **f0 em voz cantada separada pelo Demucs tem erro de oitava.** Mitigação: usar a flag
   `voiced` do `pyin` e descartar frames não-voiced antes de comparar contorno; oitava
   errada aparece como salto de 12 semitons e é detectável.
3. **CPU apenas** — `torch.cuda.is_available()` é `False` nesta máquina. `pyin` em 10s de
   áudio é aceitável, mas não é grátis; se a rodada ficar lenta, o knob é `frame_length`.
4. **Porte para Discord depende de hospedar este Flask.** Confirmado que Activities falam
   com backend próprio via URL Mappings, então Python não é beco sem saída — mas o custo
   de hospedagem existe e não foi avaliado.

## Emenda 2026-09-12 — modo karaoke: ataques vêm do áudio, gabarito só janela (decisão (a))

**Supera** a frase do Componente 1 "ataques vêm do gabarito alinhado" e a Task 4 do plano
original. Decisão humana registrada em 2026-09-12, depois de medição.

### O problema, medido

`track_from_word_timing` devolvia `ref.onsets = inícios de palavra` (71 no job
`mimic_gab_01`) enquanto `take.onsets` são ataques do detector (163 no mesmo áudio).
`attacks` e `rhythm` comparavam populações diferentes: o gabarito pontuado contra o próprio
áudio dava **53,7** (melody 100, attacks ~44, rhythm ~0). O dial de ritmo estava morto no
modo karaoke.

### A decisão

A referência do modo karaoke passa pela **mesma** função de extração que o take —
`track_from_audio` — sobre o **recorte** do vocal isolado:

```
janela = [ words[0].start − WINDOW_PAD_S ,  words[-1].end + WINDOW_PAD_S ]   (WINDOW_PAD_S = 0,1 s)
ref    = track_from_audio(vocals_raw[janela], sr)
```

O gabarito continua obrigatório, mas só para **validar** (vazio → erro; não monotônico →
erro; sem `end` ou janela vazia → erro) e **janelar**. Os `onsets` da referência ficam
relativos ao início da janela — `score()` compara intervalos e contagens, nunca instantes
absolutos, então o deslocamento é indiferente.

Por que a folga de 0,1 s antes de `t0`: o detector precisa ver o RMS *subir*; recorte que
começa em cima do primeiro ataque perde esse ataque (medido em 2026-09-12: pad 0 pega 4 de
5 no job real; pad 0,05–0,2 pega 5 de 5). Também absorve parte do erro de ~200 ms do MFA.

### Números (medidos em 2026-09-12 no job `mimic_gab_01`, sessão de medição anterior à implementação)

| caso | antes (gabarito como onsets) | depois (opção a, pad 0,1) |
|---|---|---|
| gabarito contra o próprio vocal (self) | 40,9 (53,7 na medição da revisão de 2026-09-11 — sessões e takes diferentes; os dois são "antes") | **100,0** |
| take deslocado no tempo | 95,4 (pad 0) | **62,1** |
| take gravado na sala | 93,0 | ≈ (não re-derivado com pad 0,1) |
| take = áudio inteiro sem recorte | 87,5 | ≈ (não re-derivado com pad 0,1) |
| take com 1 clique de botão antes | 48,8 (87 de 160 ataques) | 48,8 — inalterado |

Dois números dessa tabela ficam **documentados como teto do ritmo atual**, não como bug
desta mudança:

- **62,1 no take deslocado**: `_mad_intervalos` é posicional (compara `diff` índice a
  índice até `min(len)`); com 160+ ataques um único ataque a mais ou a menos no começo
  desalinha todos os pares seguintes. Pré-existente — (a) só o expõe porque agora há ritmo
  para medir.
- **48,8 com um clique**: `track_from_audio` normaliza por pico de amostra; um clique de
  botão vira o pico e afoga o vocal abaixo de `ENERGY_MIN` (87 de 160 ataques). Varredura
  de 6 percentis no lugar do pico não resolveu. Pré-existente e separado do ritmo.

### O que fica aberto (decisão de spec seguinte, fora desta emenda)

Casamento por conjunto (cada ataque da referência procura o vizinho mais próximo no take)
foi prototipado: conserta o real (deslocado 96,6 · sala 93,0 · inteiro 87,5) mas é
**leniente demais** com os negativos — p95 do acaso sobe de 52,8 para **70,5**, esticado
1,3× vai a **92,6** (andamento errado deixa de ser punido), ruído tira **68** de ritmo
porque 432 ataques de ruído sempre acham vizinho. Só *recall* é enganável por take denso.
O candidato é **F1 (recall × precisão) + termo de andamento (razão das durações)**; o clique
entra junto (normalizar pela envoltória RMS em vez do pico, ou recortar o início do take
com `vad.py`). Prototipar numa sessão curta com as mesmas fixtures; não entra aqui.
