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

### Componente 4 — nada de deleção

Não há código de scoring legado para apagar. O marco A não toca o pipeline.

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
