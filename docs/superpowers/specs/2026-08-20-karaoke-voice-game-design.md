# Motor de jogo de karaoke com tracking de voz em tempo real

Data: 2026-08-20
Linhagem alvo: `mvp-pipeline-runner` (checkout principal)
Música de teste: `jobs/publi-bet` ("Publi de Bet")

## 1. Objetivo

Transformar um job já processado do pipeline em uma partida jogável no navegador: o
jogador canta ao microfone, o jogo compara a voz dele com a melodia da música em tempo
real e pontua. Sem app, sem build step, sem conta de usuário.

## 2. Decisões fechadas

| Decisão | Escolha | Observação |
| --- | --- | --- |
| Onde roda | Navegador, dentro do app Flask existente | reusa stems, `analysis.json` e templates |
| Melodia alvo | **ROSVOT** (transcrição de notas de canto) | reafirmada pelo usuário após ser apresentado o custo e a alternativa por CREPE |
| Pontuação | Barras de nota estilo SingStar | barra por nota, traço da voz por cima |
| Playback | Instrumental + vocal guia com slider 0–100%, velocidade 0.25×–2× | o slider cobre os três modos pedidos |
| Gamificação | Tela de resultado, sem persistência | sem recorde, sem ranking, sem multiplayer |

Sobre o ROSVOT: a alternativa (aproveitar o F0 do CREPE, que já roda em
`scripts/s03b_lyrics_align.py:1529` e hoje é descartado) foi apresentada com o custo
comparado e recusada duas vezes. Fica registrada aqui como plano B atrás do mesmo
contrato, não como pendência de discussão.

## 3. Linha de base medida (`jobs/publi-bet`)

Medido em 2026-08-20 sobre `analysis.json` e `vocals.wav` do job:

```
52 linhas · 324 palavras · 474 sílabas · 176,2 s de áudio
duração da sílaba:    min 0,002 s   p50 0,080 s   p90 0,221 s   max 1,164 s
sílabas >= 120 ms:    149 de 474 (31%)
sílabas em linha rap: 144 de 474 (30%)
estilos de linha:     chorus 16 · rap 14 · verse 6 · outro 6 · prechorus 4 · bridge 4 · intro 2
confiança da sílaba:  474 de 474 entre 0,75 e 0,85 (p50 0,82)
cobertura na linha do tempo: start/end 53,7 s · phonetic 99,8 s · spans de linha 145,3 s
```

Três consequências de projeto saem daí:

1. **A sílaba não é a unidade de pontuação.** Com mediana de 80 ms, dois terços das
   sílabas não têm frames suficientes para medir afinação — um detector de pitch precisa
   de ~40 ms de janela só para enxergar o período de uma voz grave.
2. **A geometria da barra vem da nota, não do span da sílaba.** Os spans são recortados
   no núcleo vocálico (`karaoke_start_policy: vowel_nucleus`, mínimo de 1,7 ms) e cobrem
   só 53,7 s dos 176,2 s. Barras construídas neles seriam fatias com buracos. As notas do
   ROSVOT são onset-a-offset e contíguas.
3. **Filtrar sílaba por `confidence` está fora.** As 474 estão entre 0,75 e 0,85 — o campo
   não separa nada nesta música. Filtro que nunca reprova ninguém é cerca decorativa.

## 4. Dados: do ROSVOT ao navegador

### 4.1 Contrato `melody.json`

O jogo nunca fala com o ROSVOT. Ele lê um arquivo, por job:

```json
{
  "job_id": "publi-bet",
  "source": "rosvot",
  "generated_at": 1786735110,
  "notes": [
    {"start": 12.34, "end": 12.78, "midi": 62,
     "syllable_id": "L003_W001_S002", "line_id": "L003",
     "text": "ma", "style": "chorus"}
  ]
}
```

- Uma entrada por nota cantada, ancorada nas sílabas de `analysis.json` por sobreposição
  temporal. `syllable_id` e `line_id` são os ids que o `analysis.json` já usa
  (`L001_W001_S001`), não índices posicionais. `style` é copiado da linha (usado para
  decidir a pista de pontuação).
- Nota sem sílaba correspondente é descartada e **contada** no log (nota órfã).
- Sílaba sem nota confiável simplesmente não aparece na pista de afinação. O jogo não
  cobra o que não sabe medir.
- Trocar o produtor (ROSVOT → CREPE → outro) muda apenas o campo `source`.

### 4.2 Produtor: `scripts/s05b_melody.py`

Novo estágio entre `s05_analyze` e `s06_generate_ass` em `build_stage_plan`
(`scripts/pipeline_runner.py:130`). Entrada: `vocals.wav` + `analysis.json`. Saída:
`melody.json` na raiz do job.

Job antigo sem `melody.json`: a tela do jogo informa e mostra o comando para gerar. Não
se roda um modelo de GPU dentro de um request HTTP.

### 4.3 Rotas

- `GET /job/<id>/melody.json` — serve o arquivo, 404 com mensagem acionável se ausente.
- `GET /job/<id>/game` — a tela (`templates/game.html`).
- `GET /job/<id>/audio/<stem>` — **já existe** (`server.py:1448`), serve `vocals` e
  `instrumental`.

## 5. Runtime no navegador

### 5.1 Arquivos

| Arquivo | Responsabilidade |
| --- | --- |
| `templates/game.html` | markup das três telas |
| `static/game-pitch.worklet.js` | MPM/NSDF no AudioWorklet (~60 linhas) |
| `static/game-scoring.js` | funções **puras** de pontuação, testáveis fora do navegador |
| `static/game.js` | relógio, render em canvas, playback, calibração, os quatro extras |

Sem bundler e sem dependência nova: o Flask serve estático puro e o frontend atual é JS
simples. Detector de pitch escrito à mão custa menos que introduzir um build step.

### 5.2 Captura

`getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false,
autoGainControl: false } })`. Supressão de ruído e AGC deformam o sinal e envenenam o
detector — ficam desligados de propósito.

O worklet acumula janela de 2048 amostras com hop de 512 (~11 ms a 48 kHz) e roda
MPM/NSDF na faixa de 65 a 1000 Hz, emitindo `{ t, hz, clarity }`.

### 5.3 Playback

Dois elementos `<audio>` (instrumental e vocals) via `MediaElementSource` → `GainNode`:

- Slider de voz guia 0–100%. 0% é só instrumental; 100% reconstrói a mistura original
  (o Demucs é uma decomposição, `scripts/s02_demix.py:165`).
- Velocidade 0.25× / 0.5× / 0.75× / 1× / 1.5× / 2× via `playbackRate` nos dois elementos,
  com **`preservesPitch = true`** — sem isso a música desafina junto com a velocidade e a
  melodia alvo passa a mentir.
- O instrumental é o relógio mestre. Watchdog a cada 1 s: se a diferença entre
  `vocals.currentTime` e `instrumental.currentTime` passar de 30 ms, corrige o vocal.

## 6. Pontuação: duas pistas

Toda sílaba pontua alguma coisa, em uma de duas moedas.

**Pista de afinação** — notas com duração >= 100 ms, em linhas que não são `rap`:

```
mic_midi = 69 + 12 * log2(hz / 440)
diff     = ((mic_midi - alvo_midi + 6) mod 12) - 6      // oitava não conta
frames   = os com clarity > 0.5 dentro de [start + 40ms, end]
acerto   = |diff| <= 1 semitom
fração   = frames_acertados / frames_totais_da_janela
nota     = fração < 0.25 ? 0 : round(100 * fração)
```

Os 40 ms iniciais são descartados: o ataque da sílaba é ruído para o detector.

O dobramento de oitava resolve dois problemas com uma linha — erro de oitava do detector
deixa de quebrar o jogo, e homem canta linha de mulher sem tomar zero.

**Pista de ritmo** — notas < 100 ms e **todas** as linhas `rap`: acerto por ataque de voz
dentro de ±120 ms do início da nota, valendo **50 pontos** (metade de uma nota de afinação
perfeita). Sem esse teto, uma linha de rap renderia mais que um refrão bem cantado. A tela
mostra `RITMO` nessas linhas, em vez de fingir que mediu afinação.

O corte de 100 ms se aplica à **nota do ROSVOT**, não ao span da sílaba — só dá para saber
a divisão real das duas pistas depois da Etapa 0. Como referência do que esperar, medido
nos spans de sílaba da Publi: 168 de 474 têm >= 100 ms, e 130 de 474 são simultaneamente
>= 100 ms e fora de linha `rap`. As notas do ROSVOT devem ser mais longas que isso, então
esses números são o piso, não a previsão.

**Combo e final:** notas consecutivas com pontuação >= 50 acumulam combo; multiplicador
`min(1 + combo/10, 2)`, aplicado aos pontos da nota. Nota final = soma obtida / soma
máxima, onde a soma máxima é a partida perfeita: todas as notas em 100 (ou 50, no ritmo)
**com o combo nunca quebrado**, portanto com o mesmo multiplicador acumulado. Converte em
letra (S/A/B/C/D).

## 7. Os quatro tratamentos de mundo real

Todos foram aprovados para a primeira versão.

**7.1 Duas pistas** — descrito acima. Sem ele, 30% da Publi é rap sem pontuação e a
maioria das sílabas fica muda na tela.

**7.2 Calibração automática de latência.** Após a primeira linha cantada, correlaciona os
onsets do microfone com os onsets das notas numa janela de ±300 ms e acha o deslocamento
que maximiza o casamento. Oferece: "seu áudio está 120 ms atrasado — aplicar?".
O padrão inicial vem de `ctx.outputLatency + ctx.baseLatency`. **O slider manual de
±200 ms permanece e continua ajustável durante a música** — fone Bluetooth muda de
latência no meio da partida, e nenhum valor medido uma vez sobrevive a isso.

**7.3 Detecção de vazamento do microfone.** Dois segundos antes da primeira nota, com a
música tocando e o jogador calado, mede a energia que entra no mic. Acima do limiar:
"estou ouvindo a música pelo seu microfone; use fone ou baixe a voz guia". Detecta e
avisa — não tenta cancelar. É o modo de falha que arruína a partida sem ninguém perceber,
porque o jogo passa a pontuar o cantor original.

**7.4 Transposição oferecida.** Após ~8 notas na pista de afinação, se a mediana do erro
for estável e diferente de zero, oferece transpor o alvo. **Oferece, não aplica** —
aplicar sozinho transformaria desafinação consistente em nota cheia, que é exatamente o
que o jogo deveria acusar.

## 8. Telas e erros

**Antes da partida:** modo de playback, velocidade, e um teste de microfone que mostra ao
vivo a nota detectada. Quem não vê o mic funcionando antes de começar culpa o jogo depois.
O aviso de vazamento aparece aqui.

**Durante:** linha atual e a próxima, faixa de notas rolando (~4 s de janela), traço da
voz, combo, pontuação. Sliders de latência e de voz guia sempre acessíveis.

**Depois:** porcentagem, letra, maior combo, e as linhas ordenadas da pior para a melhor.
Nada é salvo em disco.

**Erros com tela própria:** microfone negado; navegador sem AudioWorklet; `melody.json`
ausente (com o comando para gerar); job sem `instrumental.wav`.

## 9. Provas

Cada prova tem controle negativo. Cerca que nunca foi vista vermelha não é cerca.

**`tests/test_melody.py`**
- Vocal sintético de 220 Hz → o estágio emite MIDI 57.
- **Controle negativo:** com 261,6 Hz o mesmo assert precisa ficar vermelho.
- Cardinalidade antes do veredito: `len(notes) > 0` antes de qualquer outra asserção.
- Toda nota cai dentro do span de alguma linha do `analysis.json`.

**`tests/game-scoring.test.mjs`** (`node --test`, sem framework)
- Frames a 3 semitons do alvo → 0.
- Frames dentro de ±1 semitom → 100.
- **Controle negativo:** lista de frames vazia → *miss*, nunca 100. É o caso
  `[].every(...)` que fica verde no conjunto vazio.
- `foldSemitone`: +11 semitons e −1 semitom devem dar o mesmo resultado.
- Pista de ritmo: ataque 80 ms antes do início da nota → 50; ataque 300 ms depois → 0.
- Uma linha de rap perfeita não pode pontuar mais que a mesma quantidade de notas de
  afinação perfeitas — o teto de 50 é asserção, não comentário.

**Detector de pitch**
- Senoide sintética → dentro de ±0,3 semitom.
- **Controle negativo:** silêncio → `null`, nunca uma nota inventada.

**Prova de campo (Publi)**
- Rodar `s05b_melody.py` em `jobs/publi-bet` e publicar três números com denominador:
  quantas notas saíram, quanto dos 145,3 s de span de linha elas cobrem, e quantas ficaram
  órfãs.
- Jogar o refrão de ponta a ponta.

## 10. Ordem de execução

**Etapa 0 — o ROSVOT tem que provar que existe.** Não há ROSVOT neste repo: nem pesos, nem
env, nem código. `scripts/03b_rosvot_inference.py` na linhagem `master` é um placeholder de
40 linhas que escreve `[]`, e `docs/project-notes/karaoke-phoneme-word-drift.md` registra o
plano SOFA/ROSVOT como derrubado. Antes de qualquer linha do jogo: subir o modelo, rodar na
Publi, registrar o schema real de saída e os três números da prova de campo. Todo o resto
depende desses números, e não o contrário.

Depois: `s05b_melody.py` → rotas → scoring puro com testes → worklet de pitch → render e
playback → os quatro tratamentos → telas de erro.

## 11. Fora de escopo

- Persistência: recorde, histórico, ranking, conta de usuário.
- Multiplayer, duelo, dois microfones.
- Reaproveitar o `melody.json` na renderização do vídeo (`s06`/`s06b`).
- Filtro de sílaba por `confidence` — medido e descartado, ver §3.
- Cancelamento de vazamento do microfone (só detecção e aviso).
- Aplicação automática de transposição (só oferta).
