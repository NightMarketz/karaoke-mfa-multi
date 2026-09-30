# Cena reativa: loop de fundo que conta uma história guiada pela música — desenho

Data: 2026-09-30. Base: `edaa4fa4`. Destino: **clipe MP4 do karaokê** (render
offline, legenda ASS queimada) — não o player ao vivo nem o jogo de festa.

## O que é

Um fundo em vídeo que repete uma pequena história em ciclo, e a música decide
quando cada ato acontece. Primeira cena, `guts_camp`:

1. **CALMO** — Guts acampado à meia-noite, fogueira pequena.
2. **TENSÃO** — a marca sangra, a brasa cresce e ilumina demônios à espreita.
3. **CLÍMAX** — muitos demônios revelados; a aura da Besta vaza.
4. **ESCURO** — a escuridão engole tudo e a cena recomeça em CALMO.

## Decisões (tomadas no brainstorm)

| Pergunta | Decisão |
|---|---|
| Onde toca | MP4 renderizado, junto da ASS queimada |
| O que move a história | Energia do stem instrumental (`no_vocals.wav`), automática |
| Como fazer as camadas | 4 variantes de quadro inteiro (Qwen-Image-Edit), cada uma um loop Wan, misturadas por crossfade |
| Onde fica a letra | **Já mora no topo** em produção: o 09 escreve `\an2\pos(640,60+110·camada)` — camada 0 nas linhas 8–48, camada 1 em 118–158 de 720 (medido). Nada a mudar |
| Qual cena por música | Parâmetro explícito `--scene`; sem ele, fundo atual |

## Arquitetura

### 1. Pacote de cena (feito à mão, uma vez por cena)

`input/scenes/<nome>/` (gitignored, como o resto de `input/`):

```
calmo.mp4  tensao.mp4  climax.mp4  escuro.mp4   # mesma duração, fps e resolução
fogo_mask.png                                   # branco = região da fogueira
scene.json                                      # opcional
```

Produção, fora do pipeline:

1. Imagem-mestre com a LoRA do personagem (prompt abaixo).
2. Três edições no Qwen-Image-Edit a partir da mestre: tensão, clímax, escuro.
   O edit preserva composição e identidade — é isso que faz as variantes
   alinharem pixel a pixel.
3. Cada imagem passa por `scripts/teste_loop_fundo.py --image <png>` (loop fecha
   por construção: mesma imagem em start/end). Mesmo número de quadros nos 4.
4. `fogo_mask.png` pintada à mão sobre a mestre.

**Composição exigida da mestre** — a letra mora no quarto superior. Frase de
composição do prompt, no lugar da original:

> Campfire in the lower third near the center, figure slightly left of center.
> Upper quarter of the frame is empty dark night sky and bare treetops, no
> creatures there. Demonic creatures only at the left, right and lower edges.

Nas edições, a aura pode subir, mas escura.

### 2. Partitura — `karaoke/scene_score.py` (função pura)

`score(rms, frame_dur, fps, duracao) -> (estados[N], pesos[N,4], ganho_fogo[N])`

**Envelope.** RMS de `onset.compute_rms` (10 ms) → média móvel de 1,5 s →
normalização pela própria música: `e = clip((x − p10) / (p90 − p10), 0, 1)`.
Se `p90 − p10` for ~0 (silêncio/tom constante), `e = 0` em tudo.

**Máquina de estados** ("sustentado" = condição contínua por esse tempo):

| De → Para | Condição | Mín. no estado de origem |
|---|---|---|
| CALMO → TENSÃO | `e > 0,45` sustentado 1 s | 4 s |
| TENSÃO → CLÍMAX | `e > 0,75` sustentado 2 s | 4 s |
| TENSÃO → CALMO | `e < 0,30` sustentado 3 s | — |
| CLÍMAX → ESCURO | `e < 0,55` **ou** 20 s em CLÍMAX (teto) | 3 s |
| ESCURO → CALMO | 2,5 s fixos | — |

Todos os limiares e durações são constantes nomeadas no topo do módulo.

**Pesos alvo por estado** (ordem calmo, tensão, clímax, escuro):

- CALMO `(1,0,0,0)`
- TENSÃO `(1−w, w, 0, 0)` com `w = 0,4 + 0,6·e` — revelação contínua
- CLÍMAX `(0,0,1,0)`
- ESCURO `(0,0,0,1)`

Os pesos seguem o alvo por rampa linear: 1,2 s padrão; 0,6 s ao entrar em
ESCURO; 2 s ao voltar a CALMO. Invariante: soma = 1 em todo quadro.

**Fogueira.** `ganho_fogo = 1 + 0,25·decai(onsets)`, onsets de
`onset.detect_onsets`, decaimento exponencial de 0,3 s.

### 3. Compositor — `scripts/08c_scene_background.py`

`--job-id X --scene <nome>`:

1. Lê `no_vocals.wav` (`paths.demucs_out_dir(job)`) e a duração dele.
2. Chama a partitura no fps dos loops.
3. Decodifica os 4 loops por pipe do ffmpeg (rawvideo), índice de quadro
   `i mod n_loop`; mistura em numpy `Σ pesos·quadro`; multiplica a região da
   máscara por `ganho_fogo`; codifica por pipe em
   `step_output(job, "08_background")/background_scene.mp4`.
4. Escreve ao lado `background_scene.json` = `{"scene": nome}`.

Falha em qualquer passo: sai com erro e não deixa `.mp4` parcial (escreve em
temporário e renomeia no fim). Sem pacote de cena → erro claro nomeando o
arquivo que falta.

### 4. Integração

- `karaoke/paths.py`: `background_scene_mp4(job)`.
- `scripts/09_video_rendering.py`: recebe `--scene <nome>` e escolhe o fundo por
  `fundo_do_job`, que só usa `background_scene.mp4` se `--scene` veio, o sidecar
  diz o mesmo nome e o MP4 não é mais velho que `no_vocals.wav`; senão cai no
  PNG (ou chapado) e o rótulo impresso diz por que a cena foi ignorada. Bounce
  continua igual.
- `karaoke/render_cmd.py`: com fundo em vídeo, `fps=25` é o primeiro filtro — o
  fps do loop não dita o do MP4 final.
- `run_pipeline.py`: `--scene <nome>` opcional; quando presente, roda o 08c
  depois do 08b e repassa `--scene` ao 09. O 08c apaga a saída antiga antes de
  compor.

## Verificação

**`tests/test_scene_score.py`** — envelopes sintéticos; cada teste declara
quantos quadros/transições examinou, e zero é falha.

1. Silêncio → N de N quadros em CALMO, peso calmo = 1.
2. Subida → platô → queda → sequência exata CALMO, TENSÃO, CLÍMAX, ESCURO, CALMO.
3. Alto constante 60 s → todo CLÍMAX ≤ 20 s e ≥ 1 ciclo completo.
4. Oscilando em volta de 0,45 → nenhum estado abaixo da própria duração mínima.
5. Soma dos pesos = 1 em todos os quadros.

Controle negativo (parte do teste): remover o teto → 3 fica vermelho;
remover mínimo e histerese → 4 fica vermelho. Restaurar.

**Compositor, fumaça** — 4 loops sintéticos de cor chapada (R, G, B, preto),
64×36, 3 s, partitura roteirizada: cores esperadas nos quadros-chave (±2
níveis); duração da saída = duração do áudio (ffprobe) e maior que o loop.
Controle negativo: trocar a ordem dos loops → falha.

**Portão real** (números são triagem; o olho decide, guia §2.7):

- `medir()` de `teste_loop_fundo.py` com a faixa parametrizada — topo
  ≈ `(0.0, 0.25)` — nas 4 variantes do `guts_camp`: brilho máximo e
  respiração da faixa, 4 de 4 reportados.
- Uma música real: gráfico de `e` com os estados sobrepostos, conferido
  ouvindo; brilho máximo da faixa do topo no vídeo final como "X de N quadros
  acima de Y"; tira de contato.
- Limiares da faixa: calibrados no primeiro pacote e registrados aqui, não
  inventados antes.

## Fora do escopo

- Escolher a cena pela letra — até existir mais de uma cena.
- Mais de uma cena por música.
- Automatizar o pacote (LoRA → edits → loops) — manual até a segunda cena.
- Reação ao vivo no navegador / jogo de festa.
