# Guia: animação 2D de personagem com IA — estado da arte em setembro de 2026

Escrito em 06/09/2026 para esta máquina (Radeon 8060S gfx1151, ROCm no Windows, ComfyUI 0.34, 52 GB livres).
Etiquetas: **[V]** verificado nesta pesquisa (fonte no fim); **[I]** inferido, raciocínio à mostra; **[L]** lembrado, não conferido. Preços e "benchmarks" de blog são **indício**, não prova.

> **Validado em 06/09/2026.** 60 afirmações deste guia foram conferidas contra a fonte (instalação real, arquivos no HF, READMEs oficiais, medição na GPU): **51 confirmadas, 6 erradas, 2 imprecisas, 1 pendente**. As erradas já estão corrigidas no texto abaixo e listadas em §8.1. Nada aqui é "verificado" por lembrança.

---

## 1. O que mudou e por que a nossa rota falhou

- Até 2024 o processo era "SD + ControlNet por frame" ou "AnimateDiff". Em 2026 o que domina é **referência-para-vídeo**: o modelo recebe a imagem do personagem (de 1 a **dezenas** de referências) e um vídeo ou descrição de movimento; a identidade é tratada por um ramo dedicado da arquitetura, não por um ControlNet genérico. [V: Vidu Q3 aceita até 7 refs; **Seedance 2.5 aceita até 50 entradas — 30 imagens, 10 vídeos, 10 áudios** (os 9+3+3 são do Seedance **2.0**); Veo 3.1 3 refs e Wan 2.7 grade de 9 **não foram conferidos em fonte oficial**]
- A geração de movimento saiu do esqueleto: **SCAIL-2 (Z.ai, jun/2026)** e **Wan-Animate-2 (ago/2026)** consomem o vídeo de movimento RGB direto, sem DWPose ou esqueleto intermediário, porque esqueleto é ambíguo em movimento complexo. Foi exatamente a nossa causa medida: pé sem chão, chute. [V: README do SCAIL-2 e do Wan-Animate-2]
- Anime é caso especial: modelos de vídeo são treinados em live-action e puxam para fotorrealismo; cel shading "ganha textura de pele" em um segundo de movimento. Por isso existem modelos e prompts específicos para anime. [V: morphed.app, indício de blog]

O que fizemos (SDXL frame a frame; Wan Fun Control 5B com esqueleto sintético) está duas gerações atrás do processo atual.

---

## 2. O processo atual, ponta a ponta

```
1. Design            2. Imagem-guia            3. Movimento            4. Animação                 5. Extensão/loop        6. Pós               7. QC
character sheet  ->  frame de referência   ->  vídeo de quem anda  ->  modelo ref-to-video     ->  blocos + color match ->  RIFE/upscale     ->  gates + olho
(1 a 7 vistas)       (base anime + CN +         (real, MMD/VMD,         (local: SCAIL-2 /           (81 frames, overlap 5)   deflicker, twos,     contagem de
                      IP-Adapter/LoRA +          Mixamo/Blender,         Wan-Animate-2;                                       composição           defeitos por frame
                      detailer + upscale)        mocap por celular)      pago: Kling 3 MC /
                                                                          Vidu Q3 / Seedance)
```

### 2.1 Design (character sheet / turnaround)
Objetivo: 3 a 7 vistas do MESMO personagem, mesma roupa, mesma paleta, fundo neutro. É o que alimenta o ramo de referência dos modelos de vídeo; quanto mais vistas coerentes, menos o modelo inventa o lado que não viu.
- Pago, mais usado em 2026: **Nano Banana Pro** (Gemini 3 Pro Image) e **FLUX.2 Pro** (2 a 10 referências por sheet). [V: guias selfielab; os "93%/95% de consistência" são indício]
- Local: Qwen-Image-Edit (edição com referência) [L: sem verificar tamanho e ROCm]; ou o próprio SDXL anime com ControlNet de pose por vista mais IP-Adapter da vista frontal (seção 5).
- Prompt de descrição: o README do Wan-Animate-2 recomenda gerar a descrição do personagem com um LLM a partir da imagem, no formato "aparência; fundo", sem descrever ação. [V]

### 2.2 Imagem-guia (o frame de referência em alta qualidade)
É a imagem que define tudo que o vídeo vai copiar. Pilha típica em 2026 (detalhe na seção 5): base anime + 1 a 2 ControlNets (pose + contorno ou tile) + IP-Adapter (identidade) ou LoRA do personagem + detailer de rosto e mãos + upscale 2×. São **5 a 7 modelos auxiliares** só nesta etapa.

### 2.3 Movimento (driving video)
O que substitui o nosso esqueleto FK:
- **Vídeo real** de alguém andando de lado, câmera fixa, fundo limpo, 3 a 5 s. É o que Kling, Runway Act-Two, Wan-Animate-2 e SCAIL-2 esperam. [V: Kling pede "vídeo claro com movimento facial visível" e mesma direção de rosto que a referência]
- **MMD/VMD** (MikuMikuDance): a comunidade de anime usa render de MMD como driver há anos; há mocap por vídeo (QuickMagic, OpenMMD) para gerar o VMD. [V: existência das ferramentas; uso como driver de Wan-Animate é [I]]
- **Mixamo/Blender**: render 3D do ciclo com contato no chão correto. [L]
- Regra: o modelo copia o que vê; erro de pé no driver vira erro de pé na saída.

### 2.4 Animação: modelo de vídeo com referência
Ver seções 3 (local) e 4 (pago). Parâmetros que os nós nativos expõem e que substituem nossos "gates por tentativa": `pose_strength`, `pose_start_percent` e `pose_end_percent` (soltar detalhe fino depois de ~0,7), `reference_image_strength`. [V: tooltips dos nós desta instalação]

### 2.5 Extensão, loop e deriva
- Todos geram por blocos: SCAIL-2, **81 frames** por passada com **âncora de 5** — o tooltip do nó diz literalmente "SCAIL-2 trained at 5 (81-frame chunks, 76-frame step)". [V: schema do `WanSCAILToVideo`]
- **Correção:** o "77 por extensão" que eu atribuí ao Wan-Animate era outra coisa. 77 é o `length` **default do `WanAnimateToVideo` (v1)**, não um tamanho de extensão; o `WanAnimate2ToVideo` tem `length` default **81** (832×480), e a âncora de extensão da v1 é `continue_motion_max_frames`, default **5**. [V: `comfy_extras/nodes_wan.py:1125` e `:1131`]
- Deriva entre blocos é corrigida com **color match** (nó nativo `ColorTransfer`, presente aqui) e, no Wan-Animate-2, com `continue_motion` do bloco anterior; a comunidade tem o "SCAIL Auto Extend" que faz isso em loop. [V]
- Loop de caminhada: gerar 2 ciclos e ficar com o do meio só funciona se o modelo não deriva com a distância da referência. No Fun Control 5B derivou (nosso H4d). Modelos com ramo de referência são feitos para não derivar. [I]

### 2.6 Pós-produção (o que separa "gerado" de "assistível")
- **Interpolação**: RIFE 4.x — o TheAnimeScripter lista **4.6, 4.15, 4.15-lite, 4.16-lite, 4.17, 4.18, 4.20, 4.21, 4.22, 4.22-lite, 4.25, 4.25-heavy e Rife_Elexor (mod 4.7)**; a faixa é 4.6 a 4.25, não 4.15 a 4.25. Usar exp=2, não 4, e modo ensemble. [V: repositório do TAS; a regra do exp=2 continua indício de blog]
- **Upscale anime**: ShuffleCugan, Span, AniScale 2, RTMOSR, Saryn. [V: TAS]
- **Restauro**: SCUNet e NAFNet (ruído), DeJpeg e DeH264, FastLineDarken (linha), deepDeband. [V: TAS]
- **Dedup e "on twos"**: remover frames redundantes e exibir 12 desenhos por segundo em base 24 é o padrão de anime; nossa escolha de 12 únicos × 15 repetições já segue isso.
- **Deflicker**: DaVinci Resolve Studio (pago) ou ferramentas de deflicker por IA. [L]
- **TheAnimeScripter** (AGPL-3.0) junta tudo isso numa CLI para Windows e roda em AMD via DirectML. [V]
- **Composição**: gerar personagem e fundo separados. O conjunto alfa do Wan 2.1 no `Comfy-Org/Wan_2.1_ComfyUI_repackaged` são **três** arquivos, não um: `wan_alpha_2.1_vae_alpha_channel` (253.806.246 B = 254 MB), `wan_alpha_2.1_vae_rgb_channel` (mesmo tamanho) e `wan_alpha_2.1_rgba_lora` (311 MB). [V: tamanhos exatos no HF; uso prático continua [L]]
- **EbSynth 2** (06/10/2025): propaga um frame pintado à mão para o vídeo inteiro por **síntese de textura**, não por IA — "preserves the keyframe content at pixel level". Detalhe que faltava: é **browser-based** (Chrome recomendado), com grátis até MP4 720p e Pro a US$ 20/mês para 4K e sequência PNG; há uma versão de linha de comando que roda offline. [V: CG Channel]

### 2.7 Controle de qualidade
Não mudou: pixel entre vizinhos mede movimento e tremor juntos; contagem visual de defeitos por frame é o que decide. Automatizar só com detector validado em controle negativo (o nosso de "passada" não validou).

> **Regra fixada em 10/09/2026, depois de errar oito vezes a mesma coisa.**
>
> **Diferença de pixel numa região não é prova de que a animação faz o que eu disse.** Ela sobe igual se a perna articula, se a figura muda de escala, se o enquadramento desloca ou se o brilho anda — e eu não consigo, olhando o número, saber qual foi. Métrica assim só sustenta **claim sobre pixel** ("o quadro 14 parece o quadro 1", "os dois runs são idênticos"), nunca claim sobre **conteúdo** ("passou a andar", "a câmera parou").
>
> Os oito casos, todos com essa assinatura: (1) limiar herdado do `gate.py` — janela embaralhada passou; (2) razão emenda/vizinhos — emenda sabotada pontuou **melhor** que a real; (3) ranquear por `vizinhos` — selecionou deriva de câmera, não articulação; (4) hipótese de rampa de luminância — normalizei, mudou 1%, e tratei "não é brilho" como "então é perna"; (5) "o personagem parou de andar" — era a rampa de entrada dos 5 primeiros quadros; (6) denominador — 22 quadros para 21, porque o `LoadVideo` conta o preview como quadro; (7) "load = 15,2 s" do §3 — era ruído, três vezes menor que a amplitude entre runs; (8) comparação de nitidez normalizada pela altura, no §3 — ampliava um lado e reduzia o outro.
>
> **O que decide continua sendo a tira de contato.** Nas três vezes desta sessão em que número e olho discordaram, o olho estava certo. Métrica automática só entra depois de ter sido **vista vermelha em material quebrado do mesmo tipo** — e "quebrado" quer dizer quebrado no eixo que ela alega medir, não em qualquer eixo.

---

## 3. Melhor modelo LOCAL para animar personagem com identidade fixa

| Modelo | Data | Como recebe movimento | Identidade | Tamanho local | Nós no ComfyUI 0.34 daqui | Licença |
| --- | --- | --- | --- | --- | --- | --- |
| **SCAIL-2** (Z.ai, sobre Wan2.1 14B) | jun/2026 | vídeo RGB, fim a fim (sem esqueleto); SAM3D-Body é **zero-shot**, não requisito | ramo de referência; máscara **opcional** | fp8 17,69 · int8 16,65 · mxfp8 17,15 · **nvfp4 11,02** · fp16 32,79 GB | `WanSCAILToVideo`, `SCAIL2ColoredMask`, `SCAILExtension`, `SAM3_*`, `SAM3DBody_*`, todos nativos [V] | MIT [V] |
| **Wan2.2-Animate-2** (Wan-AI) | 07/08/2026 | vídeo RGB, fim a fim; **+ controle de ponto de vista por texto**, que desacopla a câmera do driver | ramo de referência, `reference_image_strength` | base e **distill oficial**: int8 16,65 · bf16 32,79 GB (mesmo tamanho) | `WanAnimate2ToVideo`, `WanAnimate2Cache` [V] | Apache-2.0 [V] |
| Wan2.2-Animate (v1) | set/2025 | esqueleto DWPose + face opcional | ramo de referência | fp8 17,3 GB (Kijai v2) | `WanAnimateToVideo` [V] | Apache-2.0 |
| LTX-2.5 (Lightricks, 22B) | ago/2026 | prompt e keyframes; multi-shot nativo; LoRA comunitária "Multiple Subject Reference" | por plano, não por pose | gated com aceite automático; mínimo 16 GB VRAM quantizado [V] | `LTXV*` nativos [V] | ver HF |
| Wan2.2 Fun Control 5B / VACE | 2025 | controle genérico (pose, canny, depth) | só `ref_image`, fraco | 9,3 GB (temos) | testado: H4a a H4h | Apache-2.0 |

Leitura: SCAIL-2 e Wan-Animate-2 são a mesma geração e o mesmo tipo de entrada; o SCAIL-2 foi treinado usando o Wan-Animate como um dos professores e adiciona troca de personagem, multi-personagem e máscara por SAM3. [V: README do SCAIL-2] Para 2D, nenhum dos dois publica teste em anime; o indício a favor é o Kling 3 (pago) declarar suporte a "anime e 3D" e o Wan 2.7 (API) manter cel shading, modelos da mesma família. [I] LTX-2.5 é outra categoria (cena e plano), não transfere pose.

**Recomendação local para esta máquina:** SCAIL-2 fp8 (17,7 GB) ou Wan-Animate-2 int8 (16,7 GB), mais clip_vision_h (1,26 GB), VAE do Wan 2.1 (0,25 GB) e a LoRA lightx2v de 4 steps (0,74 GB). Disco: 52 GB → ~32 GB, acima do piso de 20.
**Custo por frame: MEDIDO nesta GPU em 07/09/2026, não mais inferido.** SCAIL-2 fp8, 512×896, 4 steps com a LoRA lightx2v, cfg 1.0:

| comprimento | estado | s/frame | n |
| --- | --- | --- | --- |
| 21 frames | quente, instância limpa | **6,90 · 7,08 · 9,09** — média 7,7, faixa 6,9 a 9,1 | 3 |
| 21 frames | frio (inclui load) | 7,64 · 8,55 | 2 |
| **81 frames** (chunk treinado) | quente | **11,67** | 1 |
| 21 frames | quente, **logo após um run de 81** | **31,15** | 1 |

**A amplitude entre runs idênticos é de 28% da média** (2,18 s/frame entre o melhor e o pior quente). Qualquer número com casa decimal aqui é falsa precisão: o custo é **da ordem de 7 a 9 s/frame** a 21 frames e **~12 s/frame** a 81.

⚠️ **Custo de load: não é mensurável por diferença.** Eu tinha escrito aqui que load = 15,2 s (0,72 s/frame) porque um run frio menos um quente deu isso. Era coincidência: o ruído entre dois runs quentes é 2,18 s/frame, **três vezes maior** que a diferença que eu atribuí ao load. Frio (8,55) chegou a ser mais lento que quente (9,09) numa das medidas — ou seja, a ordem se inverte dentro do ruído.

⚠️ **Rodar 81 frames envenena a instância.** O run seguinte de 21 frames, mesma configuração, caiu para **31,15 s/frame** — 4× a média limpa. Não é swap (pagefile com 0,9 GB em uso, 35,9 GB de RAM livre) e o servidor estava de fato computando. Hipótese, não medição: estado do alocador depois de buffers muito maiores, nesta APU onde a memória do GPU é a do sistema. **Regra operacional: reinicie o ComfyUI ao trocar de comprimento.**

⚠️ **Armadilha do cache:** repetir o mesmo grafo com a **mesma seed** devolve do cache e reporta 0,10 s/frame — 326× mais rápido que gerar. Isso não é velocidade. Para medir a quente, troque a seed.

#### Prova real dos números acima

Meus tempos vêm do cliente (`time.perf_counter()` em volta de um polling de 2 em 2 segundos), o que embute viés para cima. O ComfyUI registra o próprio tempo no `/history` (`execution_start` → `execution_success`), que é **fonte independente**. As duas têm que fechar, e a diferença tem que caber na janela de 2 s do polling:

| seed | servidor (s) | cliente (s) | delta | s/frame servidor | s/frame cliente |
| --- | --- | --- | --- | --- | --- |
| 20261010 | 179,2 | 179,6 | +0,4 | 8,53 | 8,55 |
| 20261011 | 190,5 | 190,8 | +0,3 | 9,07 | 9,09 |
| 20261012 | 147,3 | 148,6 | +1,3 | 7,01 | 7,08 |
| **soma** | **516,9** | **519,0** | **+2,1** | | |

Os três deltas caem em [0, 2) s, como previsto. **Viés máximo do polling: 0,06 s/frame — 36× menor que a amplitude de 2,18 s/frame entre runs.** Conclusão que isso autoriza: a variação de 28% é do próprio modelo/máquina, **não é artefato da minha medição**.

**Controle negativo do cheque** (pareando servidor de um run com cliente de outro, o que tem que reprovar): −30,6 s, +43,5 s, −10,9 s — os três fora de [0, 2). O cheque discrimina; não é verde universal.

*Reproduzir:* `python smoke_scail.py 21` e depois ler `http://127.0.0.1:8188/history`. Logs desta medição em `C:/rk/sfr_limpo.log` e `C:/rk/smoke_scail.log`.

#### A 832×1216 (resolução de trabalho): medido, e o custo é quadrático nos pixels

| seed | estado | s/frame |
| --- | --- | --- |
| 20261020 | frio | 42,73 |
| 20261021 | quente | 42,88 |
| 20261022 | quente | 43,67 |

Faixa 42,7 a 43,7 — amplitude de **2,2% da média**, dez vezes mais estável que a 512×896 (28%).

**A regra de três estava errada por 2,5×.** Antes de medir eu previ 17 s/frame (faixa 15–26) assumindo escala linear nos pixels. Medido, a razão 832×1216 / 512×896 fica entre **4,7× e 6,3×** conforme o pareamento (5,00 frio-com-frio, 5,63 pelas médias, 6,11 pelas medianas) para apenas **2,21× de pixels**. Linear previa 2,21; quadrático prevê 2,21² = 4,88. Os dados são **compatíveis com quadrático** — o que casa com atenção sendo quadrática no número de tokens — mas **não distinguem quadrático de um pouco pior**. Não trate 4,88 como confirmado.

**Consequência de plano:** um chunk de 81 frames a 832×1216 custaria da ordem de **1,5 h** [I: 43,3 × o fator 1,52 que o comprimento 81 impôs a 512×896], contra 15,75 min a 512×896. **Gere a 512×896 e faça upscale 2× no pós** (§2.6): a resolução final não paga o preço de ser gerada.

*Prova real desta medição, com uma reprovação:* deltas cliente−servidor de +0,8, +1,6 e +2,8 s. O terceiro **reprova** o predicado [0, 2) fixado acima. Testei duas explicações e as duas caíram: uma requisição ao `/history` custa 0,01 s (não 0,8), e gravação de PNG não explica — o throughput implícito varia de 4,6 a 22,4 MB/s quando deveria ser ~constante. **Fica registrado sem explicação.** O viés é ≤0,3% do total e não move a conclusão de 5–6×, mas esta linha não deve ser lida como "conferida". Log: `C:/rk/sfr_832.log`.

#### A rota barata, medida ponta a ponta (07/09/2026)

Gerar a 512×896 e subir com upscaler de anime, em vez de gerar na resolução final:

| etapa | s/frame | fonte |
| --- | --- | --- |
| gerar a 512×896 | 7,7 (faixa 6,9–9,1, n=3) | medido |
| upscale 2× → 1024×1792 | **6,24** (21 de 21 frames, 2,18 min) | medido |
| **total** | **~13,9** | soma |
| *alternativa:* gerar nativo a 832×1216 | 43,3 | medido |

**3,1× mais barato — e termina com 1,81× mais pixels** (1024×1792 = 1.835.008 contra 1.011.712 do 832×1216). Num chunk de 81 frames: ~24 min (15,75 de geração + 8,4 de upscale) contra ~1,5 h do nativo.

Modelo: `RealESRGAN_x4plus_anime_6B.pth` (17.938.799 B, `ximso/RealESRGAN_x4plus_anime_6B`), em `models/upscale_models/`. O modelo é nativamente **4×**; o grafo faz `ImageUpscaleWithModel` (2048×3584) e depois `ImageScale` lanczos para o alvo. Reduzir do 4× reconstrói linha e chapado; pedir 2× a um resize só interpola. Script: `post_upscale.py`.

**Qualidade, comparada de forma justa.** Primeira tentativa minha foi enviesada: normalizei os recortes pela altura, o que ampliou o original de 512 em 1,8× e reduziu o upscale em 0,9× — o original apanhava por construção. Refeito a 1:1, reduzindo os dois ao mesmo tamanho de entrega (832×1216):

- nitidez (gradiente médio): **upscale 2,480 · nativo 2,384**
- controle negativo (o nativo borrado): **1,146** — a métrica cai, então discrimina

Os 4% a favor do upscale são menores que a diferença entre dois desenhos de seeds diferentes. **A conclusão que os dados sustentam é "não é pior", não "é melhor".** Comparação em `C:/rk/upscale_compare_1to1.png`.

⚠️ Aspecto: 512×896 × 2 = 1024×1792, razão 0,571. O 832×1216 tem 0,684. **Não são o mesmo enquadramento.**

#### 608×896: a rota barata com o aspecto certo (medido 07/09/2026)

608/32 = 19 e 896/32 = 28, e o aspecto 0,6786 fica a **0,8%** do 0,6842 do 832×1216 — o par de múltiplos de 32 mais próximo do alvo.

| seed | estado | s/frame |
| --- | --- | --- |
| 20261030 | frio | 11,32 |
| 20261031 | quente | 10,91 |
| 20261032 | quente | 11,96 |

Média quente **11,44**. Prova real: deltas cliente−servidor de +0,5, +0,9 e +0,9 s, **os três dentro de [0, 2)**. Upscale 2× → 1216×1792: **8,23 s/frame** (21 de 21, 2,88 min). Log: `C:/rk/sfr_608.log`.

**As três rotas, lado a lado:**

| rota | s/frame | entrega | pixels | aspecto |
| --- | --- | --- | --- | --- |
| gerar 512×896 + upscale 2× | **13,93** | 1024×1792 | 1.835.008 | 0,571 ✗ |
| **gerar 608×896 + upscale 2×** | **19,67** | 1216×1792 | 2.179.072 | **0,679 ✓** |
| gerar nativo 832×1216 | 43,28 | 832×1216 | 1.011.712 | 0,684 |

A rota de 608 é **2,20× mais barata que o nativo e entrega 2,15× mais pixels**, com o aspecto certo. É a recomendação.

#### A lei de escala, com validação cruzada

Custo ∝ pixels^k. De três resoluções medidas: k = 2,31 (512→608) e k = 2,18 (512→832), **média 2,25**. Linear seria 1; atenção pura seria 2. O expoente fica **acima de 2** de forma consistente, o que explica por que a regra de três errou por 2,5×.

Validação cruzada — prever 832×1216 a partir do 608×896, que não foi usado para ajustar nada:
- com k = 2,25: previsto 46,0, medido 43,28 → **+6%**
- **controle negativo**, com k = 1 (linear): previsto 21,2, medido 43,28 → **−51%**

*Qualidade das duas rotas de upscale, reduzidas ao mesmo tamanho de entrega (832×1216):* nitidez 2,480 (de 512), 2,236 (de 608), 2,384 (nativo), com o controle negativo em 1,146. **A direção inverte** entre as duas rotas — +4% numa, −6% na outra. Isso é a evidência de que diferenças dessa ordem são artefato de reamostragem (quanto mais você reduz depois do 4×, mais suaviza), **não qualidade**. As três se equivalem a olho: `upscale_compare_1to1.png` e `upscale608_compare_1to1.png`.

**Qualidade medida no mesmo smoke (07/09/2026), sem vídeo-driver:**
- 21 frames: cel shading intacto, design estável, **0 defeitos de pé em 21 de 21** — o borrão de sandália na pose de passagem, que quebrou todas as variantes do H4, não apareceu.
- 81 frames: **o modelo corta para outro plano.** Os maiores saltos entre vizinhos ficam nos frames 46→53 (pico 31,4 em 50→51) e a distância ao frame 1 sobe de ~24 (frame 41) para ~53 (frame 51), estabilizando em ~58 até o fim. De perfil andando ele passa a meio-primeiro-plano frontal, mão na cintura, e o short de barra branca vira calça com faixa vermelha.
- Leitura: **sem driver, ~46 frames de caminhada coerente** e depois o modelo inventa um corte. Para um ciclo de 12 frames isso sobra. Mas confirma que o vídeo de movimento **não é polimento, é o mecanismo** — é ele que impede o modelo de mudar de plano.
- Cuidado com a métrica: distância ao frame 1 mistura deslocamento com deriva de identidade. Aqui foi identidade mesmo, confirmado a olho; o número sozinho não separa os dois. **Aviso que faltava:** o README oficial diz que os defaults são afinados para **8× A800 a 720P**, e que 480P foi testado em **2× A800**. Uma placa só, integrada, não é o cenário de referência de ninguém — o número de s/frame desta máquina é chute até o smoke rodar.

**Resoluções treinadas (SCAIL-2):** 512p e 704p; pose-driven e replacement rendem melhor a 704p. H e W têm que ser divisíveis por 32. [V: README zai-org]

**Distill:** existe checkpoint **distilado oficial** do Wan-Animate-2 (10 steps, `guidance_scale=1.0`, Euler), do mesmo tamanho do base. Não é a mesma coisa que a LoRA `lightx2v` de 4 steps — são dois caminhos, e o oficial não custa disco extra se você baixar o distill no lugar do base. [V: README Wan-AI + arquivos no Comfy-Org]

**int8_convrot nesta GPU: MEDIDO, não suposto.** `quantize` + `F.linear` com convrot groupsize 256 rodam em gfx1151; erro relativo médio **0,0112** contra bf16, com controle negativo (quantizar outra matriz) em **1,4206** — 127× de separação, então a checagem discrimina. `supports_fast_matmul()` → `True`. **Ressalva:** `triton` não está instalado no venv-rocm e o auto-enable do backend triton em ROCm está comentado em `comfy/quant_ops.py:52`, então isso rodou pelo caminho hip/eager. Corretude confirmada, **velocidade não medida**. Continua valendo preferir **fp8_scaled**, que é o formato que já carrega aqui — 1 GB não paga descobrir o custo de velocidade na hora.

**SAM3 não é requisito.** O checkpoint existe e está publicado: `Comfy-Org/sam-3d-body` → `sam_3d_body_dinov3_bf16` (2,83 GB) ou `_int8_convrot` (1,99 GB), em `models/detection/`. Mas `pose_video_mask` e `reference_image_mask` são `optional=True` no schema do `WanSCAILToVideo`, e `replacement_mode` default é `False` (Animation Mode) — **um personagem só não precisa de máscara SAM3**. A frase anterior ("se o SCAIL-2 exigir SAM3.1, o Wan-Animate-2 é o caminho sem lacuna") partia de uma premissa falsa: não há lacuna. [V: schema do nó + arquivos no HF]

---

#### Entrega em GIF de 10 s: o formato não carrega a rota do upscale (medido 10/09/2026)

Mesmo material (ciclo de 12 quadros de `scail608_20261031`, nativo e `_up2x`), 12 fps, palettegen/paletteuse:

| conteúdo | quadros | resolução | tamanho |
| --- | --- | --- | --- |
| ciclo, loopa sozinho | 12 | 480×704 | **1,13 MB** |
| ciclo, loopa sozinho | 12 | 608×896 | 1,65 MB |
| 10 s reais | 120 | 480×704 | **13,03 MB** |
| 10 s reais | 120 | 608×896 | 19,84 MB |
| 10 s reais | 120 | **1216×1792 (a rota recomendada acima)** | **68,38 MB** |
| mesmo material em MP4 | 120 | 608×896 | 0,96 MB |
| mesmo material em WebP | 120 | 608×896 | 2,86 MB |

Re-derivação: 13,03/120 = 0,109 MB/quadro contra 1,13/12 = 0,094 — fecham dentro de 16%. **Consequência:** para entrega em GIF o upscale 2× cobra 8,23 s/frame (42% da rota de 19,67) para produzir 68 MB que ninguém abre. A rota do GIF é gerar a 608×896 e **não subir** — 11,44 s/frame. O upscale continua certo para MP4.

#### Loop sem driver: 0 de 270 janelas fecham a emenda (medido 10/09/2026)

3 seeds novas (20260940–42), 21 quadros a 608×896, 4 steps, sem driver. Custo **11,88 · 12,53 · 11,68 s/frame** (média 12,03; previ 11,44, errei 5% para baixo). Prova real cliente−servidor: deltas +1,21, +1,95, +0,92 — **3 de 3 em [0, 2)**; controle negativo pareando runs trocados, **6 de 6 fora**.

Varredura de todas as janelas de 8 a 16 quadros — **270 candidatas (3 seeds × 90)**: **nenhuma** fecha a emenda para frente. Confirma o que o §2.5 dizia: sem driver o personagem transla e translação não loopa.

**Dois cheques caíram no controle negativo, e é o que essa rodada tem de mais útil:**
1. Os limiares herdados do `gate.py` (vizinhos < 6,0, emenda < 8,0) foram escritos para ciclo FK, onde vizinhos valem ~5. No material do SCAIL-2 a 608 eles valem 0,4 a 8, e **uma janela com os quadros embaralhados passou** (vizinhos 3,58 < 6,0). Limiar herdado sem re-medir não é cerca.
2. O critério que escrevi no lugar — emenda/vizinhos ≤ 2,0 — **também não discrimina**: sabotar o último quadro deu razão **1,85**, melhor que a melhor janela real (2,31). Com movimento alto, dois quadros quaisquer do mesmo run distam o mesmo, e a razão satura.

**O que sobrou é garantia de construção, não limiar:** ping-pong (i..j, j−1..i+1) faz de *todo* par consecutivo do ciclo fechado um par que era vizinho na geração. `make_loop_gif.py --selfcheck` sabota a sequência de 3 formas (pontas repetidas, salto de 2, volta faltando) e as 3 levantam; a correta passa — **4 de 4 como previsto**.

⚠️ **`vizinhos` mede deriva de câmera, não articulação.** O 20260940 (vizinhos 0,78) e o 20260942 (vizinhos 7,75) têm a mesma articulação de perna nas tiras de contato; os 10× de diferença são o fundo e a escala derivando no 20260942. Escolher por `vizinhos` alto seleciona **deriva**, não animação. Quem decide continua sendo a tira de contato.

Scripts: `loop_pick.py` (varredura + controles), `make_loop_gif.py` (montagem + `--selfcheck`). `smoke_scail.py` agora lê `SCAIL_W`/`SCAIL_H`/`SCAIL_SEED`/`SCAIL_PREFIX` do ambiente.

---

#### Ação descrita no prompt: RETIRADO — a conclusão vinha da métrica que não mede o que dizia

**O que estava escrito aqui até 10/09/2026:** "descrever a ação é obrigatório enquanto não houver driver", com o 20260940 saindo de 0,471 para 16,538 na métrica `acao` (faixa dos pés) — 35×.

**Por que caiu:** `acao` era diferença média de pixel na faixa inferior do quadro. Ela sobe do mesmo jeito se a perna articula, se a figura muda de escala, se o enquadramento desloca ou se o brilho anda. Testei a hipótese do brilho e ela caiu (normalizar mudou 1%), e conclui que "então é perna" — **não era conclusão, era a única alternativa que eu tinha testado.** A tira de contato dos 21 quadros mostra o run de base **também andando**; o 35× media a rampa de escala, não a passada.

**O que sobra do experimento:** o custo (11,27 s/frame de média, 3 runs de 21 de 21 quadros) e a constatação, a olho, de que os dois prompts produzem caminhada. **Se descrever a ação ajuda, isto aqui não mostrou.** Continua em aberto, e para fechar precisaria de um cheque que meça articulação de verdade — ângulo de joelho, posição de tornozelo — não diferença de pixel numa faixa.

⚠️ **Rampa de entrada (isto se sustenta, é observação direta):** os ~5 primeiros quadros de todo run saem desbotados e com escala instável, nos dois prompts. Montar GIF incluindo essa faixa contamina o resultado — `loop_pick.py --skip 5`. Foi ela que me fez ler "o personagem para de andar" numa janela que começava no quadro 1; nos 21 quadros inteiros ele anda o tempo todo.

---

#### `fixed camera, no zoom, no pan` não faz o que diz (medido 10/09/2026)

Braços pareados: 3 seeds novas (20260950–52), prompt **idêntico** exceto a cláusula de câmera, intercalados por seed. 6 runs, 11,33 s/frame de média (faixa 10,91–11,92).

Os números de `deriva` e `acao` que sustentavam esta seção **saíram** junto com a métrica (ver a seção retirada acima): ambos são diferença de pixel numa região e não distinguem o que muda. O que resta, e resta em pé:

**Piso de ruído medido, e é zero.** Repeti um braço com a instância reiniciada: **21 de 21 quadros byte-idênticos** (diferença máxima 0,0). Controle: o outro braço, mesma seed, difere com média 4,29 e máxima 255. Isso é claim sobre pixel sustentado por medida de pixel — legítimo. Conclusão que autoriza: a cláusula **muda** a saída, de forma determinística.

**Mas não muda a câmera, e quem diz isso é o olho:** as tiras dos dois braços do 20260952 são **indistinguíveis**. E a evidência mais direta veio de graça na rodada anterior — o `acao608_20260942` **tinha** a cláusula e mesmo assim produziu rampa de escala e de brilho. Cláusula presente, deriva acontecendo.

Leitura: **negação em prompt não funciona sem CFG** — sem guidance não há de onde subtrair "no zoom". Consistente com o cfg 1.0 que a LoRA de 4 steps exige. Para câmera fixa de verdade, o caminho é o `pose_video` — o driver.

⚠️ **Limite deste teste:** nenhuma das 3 seeds novas apresentou o *dolly-out* que a cláusula deveria corrigir, então isto mede "ajuda em geral", não "conserta seed que deriva". A observação do 20260942 acima cobre parcialmente esse buraco, com n=1.

---

#### `pose_video` ligado e medido: dirige de verdade, e custa +60% (10/09/2026)

Fiação: `LoadVideo` -> `GetVideoComponents` -> `pose_video` do `WanSCAILToVideo` (`smoke_scail.py` com `SCAIL_POSE=<arquivo.mp4>` em `ComfyUI/input/`). O nó trunca o driver ao `length` sozinho e reduz para metade da resolução de saída. Driver usado: os 21 primeiros quadros do `luffy_h4e_15s.mp4` — **saída antiga da rota H4, com os defeitos de pé dela**; serve para aferir mecanismo e custo, não qualidade.

**As 4 previsões registradas antes acertaram.**

| medida | resultado |
| --- | --- |
| saída com driver vs sem driver (mesma seed) | **19,22** de diferença média |
| driver normal vs driver invertido no tempo | **14,95** |
| controle: sem driver vs sem driver | **0,000** |
| custo | **18,41 e 17,62 s/frame** contra 11,24 sem driver = **+60%** |

**O perfil temporal da saída é o do driver**, medido por correlação entre as séries de diferença por par (20 pares cada):

| par | correlação |
| --- | --- |
| saída normal × driver | **+0,991** |
| saída normal × driver invertido (controle) | −0,897 |
| saída invertida × driver invertido | +0,996 |
| **sem driver × driver (controle)** | **−0,036** |

O controle de baixo é o que dá valor ao de cima: sem driver a correlação é zero, então o +0,991 não é artefato da métrica. **O `pose_video` é o mecanismo, confirmado, não inferido.** As tiras de contato mostram a saída copiando a passada do driver quadro a quadro, inclusive o borrão de sandália da pose de passagem — "erro de pé no driver vira erro de pé na saída" (§2.3) agora tem medição.

⚠️ **Denominador que mentia, consertado.** Com `LoadVideo` no grafo o `run()` do `bench_anime.py` conta o **preview do vídeo de entrada** como se fosse quadro: reportou 22 para 21 pedidos, com 21 arquivos em disco. O `smoke_scail.py` agora conta só o que o `SaveImage` escreveu e informa quantas saídas de UI vieram de outros nós.

**Custo da rota do GIF com driver:** 18,0 s/frame -> 21 quadros em 6,3 min (contra 3,9 min sem). O `WanAnimate2Cache` do §6.4 promete cortar isso pela metade, mas é nó do Wan-Animate-2, **não do SCAIL** — não testado aqui.

---

#### O driver que resolveu: manequim 3D de banco livre, e o loop passou a fechar (10/09/2026)

Não é preciso filmar ninguém. **Pixabay id 127335 e 84696** entregam render CGI de caminhada; o **84696** ("Walk Running Human Corridor 3D CGI", 1920x1080, 24 fps, 21 s) é manequim branco **de perfil, corpo inteiro, pés visíveis, câmera parada, andando no lugar** — exatamente a opção "render MMD/Mixamo/Blender" do §2.3, e sem a questão de licença de filmar pessoa (Pixabay dispensa atribuição).

Reprovados no caminho, e por quê: Pexels 6454292 (close dos pés numa academia, fundo carregado) e Pixabay 127335 (figura pequena, andando na diagonal).

**Preparo do driver, resolvido pelo pixel e não por chute:** a coluna do personagem foi achada pela imagem de movimento (média das diferenças entre vizinhos), dando x 836..1161, centro 1000. Recorte 733x1080 em x=634 -> aspecto **0,6787** contra 0,6786 do alvo. Reamostrado para **12 fps**, que é o fps do GIF — driver a 24 fps num GIF de 12 sai em câmera lenta.

**O período do driver é medido, não suposto: 14 quadros.** Distância ao quadro 1 por deslocamento k: vizinho imediato 4,44; k=14 dá **0,32**; k=28 (segundo harmônico) 0,31; máximo 6,25. Separação de 20x — o cheque discrimina.

**Previsões registradas antes: 3 de 4.**

| # | previsão | medido | |
| --- | --- | --- | --- |
| 1 | corr(saída, driver) > 0,9 | **+0,759** | ✗ |
| 2 | janela de 14 fecha para frente (razão ≤ 1,5) | **0,90** | ✓ |
| 3 | custo 17–19 s/frame | 17,71 | ✓ |
| 4 | 0 a 2 defeitos de pé em 21 quadros | 0 a 1, a olho | ✓ |

A correlação de 0,759 é menor que os 0,991 do driver H4 — esperado: o H4 era o próprio personagem no mesmo enquadramento, o manequim tem outras proporções. Continua bem acima dos dois controles (sem driver 0,201, driver invertido 0,336).

**O resultado que muda o entregável:** com driver periódico o loop **fecha para frente**, e o ping-pong deixa de ser necessário.

**A prova não é a razão — razão dividida por movimento sofre da mesma doença do §2.7.** O que sustenta é comparação **dentro do mesmo run**, onde a quantidade de movimento é constante (vizinhos 12,4 a 13,7 em todas as janelas), com a emenda **crua**:

| seed | n=10 | n=12 | **n=14 (o período)** | n=16 |
| --- | --- | --- | --- | --- |
| 20260950 | 19,74 | 19,88 | **11,47** | 13,25 |
| 20260951 | 20,37 | 21,33 | **12,39** | 12,87 |
| 20260952 | 21,65 | 22,02 | **12,97** | 14,66 |

O mínimo cai exatamente no período que foi medido **no driver, antes de gerar** — previsão que podia ter falhado e não falhou, em 3 de 3 seeds. Contra os runs sem driver, também sem normalizar: **11,47 · 12,39 · 12,97** contra **22,80 · 27,08 · 31,49**.

`make_loop_gif.py --forward` monta o loop direto e **mede** a emenda antes de gravar (sem ping-pong não há garantia de construção). Os dois controles acima são o mesmo predicado visto vermelho, com saída 1.

Entregável: 14 quadros, 480x704, 12 fps, **1,75 MB** e loopa sozinho; versão de duração fixa com 8 ciclos inteiros = 9,33 s, 14,03 MB.

**As 3 seeds com esse driver (10/09/2026), e as 4 previsões acertaram:**

| seed | s/frame | corr com o driver | vizinhos | emenda | razão | loop de 14 |
| --- | --- | --- | --- | --- | --- | --- |
| 20260950 | 17,71 | +0,759 | 12,690 | 11,471 | **0,90** | fecha |
| 20260951 | 17,89 | +0,725 | 13,110 | 12,387 | **0,94** | fecha |
| 20260952 | 17,81 | +0,830 | 13,700 | 12,966 | **0,95** | fecha |

**3 de 3 fecham.** Controle na mesma rodada — as **mesmas** 3 seeds nos runs sem driver, mesma janela de 14: razão 3,87 · 3,92 · 4,05, **3 de 3 reprovam**. Separação de ~4x entre as duas populações.

A olho, os 3 são ciclo de caminhada limpo com contato de pé correto; o defeito residual é oscilação leve do colete (o painel vermelho da frente some em um ou dois quadros), não pé. GIFs de 1,75 · 1,80 · 1,97 MB.

---

## 4. Melhor modelo PAGO (API) para o mesmo problema

| Serviço | Entrada de referência | Movimento | Anime | Preço (indício, ago/2026) |
| --- | --- | --- | --- | --- |
| **Kling 3.0 Motion Control** | 1 imagem; a página oficial recomenda **múltiplos ângulos** (frente, perfil, expressões) ou um clipe curto | "works seamlessly on human, **anime**, and 3D characters as long as the style remains consistent" [V: citação literal da página oficial]. **Duração 3–30 s: não consta na página oficial** — retirado | sim, oficial | **Oficial é em créditos**: 6/s a 720p, 8/s a 1080p sem áudio; 9/12 com áudio nativo; +2 voice control. USD/s (0,067 a 0,14) é **preço de revenda**, não da Kling [V: guia oficial 06/02/2026; USD de agregadores] |
| **Vidu Q3** | 1 a 7 referências (personagem, objeto, cena) | prompt / ref-to-video | forte em cel shading e linha, segundo testes de blog | US$ 0,056 a 0,123/s [V: agregadores] |
| **Seedance 2.5** | **até 50 entradas: 30 imagens, 10 vídeos, 10 áudios.** Os "9 imagens + 3 vídeos + 3 áudios" que eu tinha aqui são do **Seedance 2.0**, não do 2.5 | prompt + refs de vídeo | bom com pacote de refs | US$ 0,231/s [V: agregadores — não conferido em página oficial] |
| Veo 3.1 | 3 imagens ("Ingredients") | prompt | generalista | mais caro que Kling [V: elser] |
| Runway Act-Two | 1 imagem ou clipe | vídeo de performance (rosto, corpo, mãos) | qualquer personagem [V: Runway help] | ver Runway |
| Wan 2.7 (API Alibaba) | grade de 9 imagens | prompt e ref | mantém cel shading (indício) | API; pesos não abertos [V] |

**Recomendação paga para "personagem meu, movimento meu":** Kling 3.0 Motion Control (pose de vídeo real, anime declarado); para cenas com mais de um personagem ou pacote de referências, Seedance 2.5 ou Vidu Q3.
Custo de um ciclo de 5 s: Kling ~US$ 0,4 a 0,8; Vidu ~US$ 0,3 a 0,6; Seedance ~US$ 1,2. [I a partir dos preços acima]

---

## 5. A imagem-guia: modelos base, ControlNets, IP-Adapter, LoRA e o resto

### 5.1 Base anime (SDXL e além)
- Família Illustrious: **Illustrious-XL** (temos a v1.0 em disco, 6,5 GB; licença = a **do SDXL base**, `license_name: sdxl-license`, ou seja CreativeML Open RAIL++-M — **uso comercial liberado**; a própria licença diz *"Licensor claims no rights in the Output you generate using the Model"*, com as restrições de uso do Anexo A), **NoobAI-XL 1.1**, **WAI-illustrious** (o "daily driver" dos guias japoneses de 2026), **Animagine XL 4.0** (8,4 M de imagens de anime — número **exato** no README; mas é **retreino a partir do SDXL 1.0**, não "do zero"; corte de conhecimento 07/01/2025; licença openrail++). [V]
- ⚠️ **NoobAI-XL: proibição comercial explícita.** O README não confirma as "13 M imagens" que eu tinha escrito — diz apenas "latest full Danbooru and e621 datasets". E a licença (fair-ai-public-license-1.0-sd + termos próprios) diz: *"We prohibit any form of commercialization, including but not limited to monetization or commercial use of the model, derivative models, or **model-generated products**"*. Se o karaokê tem qualquer fim comercial, NoobAI está fora — e a proibição alcança a **imagem gerada**, não só o modelo. [V: README no HF]
- ⛔ **Anima 2B: não comercial. Fora deste projeto se ele monetiza.** Repositório `circlestone-labs/Anima`, frontmatter `license_name: circlestone-labs-non-commercial-license`. A CircleStone Labs Non-Commercial License v1.2 abre com *"freely available for your **non-commercial and non-production use**"* e define Non-Commercial Purpose como uso *"only so far as you do not receive any direct or indirect payment arising from the use of the CircleStone Model, or Derivatives"*. Armadilha: a licença diz que **Outputs não são Derivatives** — mas a restrição morde no **uso do modelo**, não na classificação da imagem. Gerar frame para karaokê pago é uso comercial. [V: LICENSE.md no HF]
- Base do Anima, divergência resolvida pelo próprio repositório: `base_model: nvidia/Cosmos-Predict2-2B-Text2Image`. O hands-on da lilting estava certo; o "arquitetura própria" da doc do Comfy, não. Text encoder Qwen-3 0.6B e VAE do Qwen-Image confirmados no README. O `AnimaIPAdapterApply` **não aparece** nem na doc do Comfy nem no README do modelo — segue indício de blog. [V: README e tags do HF]
- Para este projeto o Illustrious já basta; a fraqueza medida era consistência entre frames, não qualidade da imagem.

### 5.2 ControlNets (para a imagem-guia, não para o vídeo)
- **xinsir controlnet-union-sdxl promax**: `diffusion_pytorch_model_promax.safetensors` = 2.513.342.408 B = **2,51 GB** exato. Openpose, canny, depth, lineart, tile e inpaint num arquivo só. [V: tamanho lido no HF]
- **Específicos de Illustrious**: MIC-Lab/illustriousXLv1.1_controlnet — **4 arquivos** (`canny`, `depth_midas`, `tile`, `inpainting`), **2,50 GB cada**, 10 GB se baixar todos [V: lista de arquivos no HF]; deepsea001/controlnet-openpose-illustrious-xl, atualizado em **13/07/2026** [V: existe, 607 downloads]. Em disco aqui hoje: só `controlnet-openpose-sdxl` e `controlnet-canny-sdxl-v2`, 2,4 GB cada — os genéricos. Motivo de trocar: ControlNet genérico de SDXL desloca cor no Illustrious. [V: indício de terceiros, coerente com o que vimos]
- **NoobAI ControlNet** (Civitai): coleção com openpose; o nome codifica o preprocessador e tem que casar. [V]
- Uso típico: pose (openpose) a 0,8 a 1,0 + contorno ou tile a 0,3 a 0,5, `end_percent` ~0,8. Foi o nosso H3c; funciona para imagem parada.

### 5.3 Identidade sem treinar: IP-Adapter
- **ComfyUI_IPAdapter_plus** (cubiq) é a implementação canônica; para SDXL/Illustrious: ip-adapter-plus (roupa e estilo) e ip-adapter-faceid-plusv2_sdxl + LoRA correspondente (rosto). Precisa de CLIP Vision. [V: blogs 2026]
- Receita mais citada em 2026: IP-Adapter FaceID (rosto) + ControlNet (pose) + detailer de rosto e mãos → "80 a 95% de consistência". [V: indício de blog]
- É custom node. Se a regra do projeto é "sem custom node", a alternativa é a LoRA (5.4).

### 5.4 Identidade treinada: LoRA do personagem
- **SDXL/Illustrious**: 20 a 50 imagens; OneTrainer ou kohya. ROCm no Windows: os guias são Linux; não verifiquei treino de LoRA em ROCm Windows. [V: números; [L]: viabilidade aqui]
- **Wan 2.2 (vídeo)**: o musubi-tuner **lista Wan2.1/2.2** e pede **12 GB de VRAM para imagem, 24 GB para vídeo** (números confirmados no repositório), 64 GB de RAM recomendados. 25 a 30 imagens com legenda por imagem, rank 32 (alpha 16), LR ~2e-4 vêm de guias agregados, não do repo. **ROCm/AMD: não documentado.** A instalação do musubi indica CUDA 12.4 (`cu124`) e não oferece alternativa AMD — não achei suporte, o que não é o mesmo que não existir. Esta GPU tem 89,4 GiB visíveis, então o gargalo não é VRAM: é a toolchain. Wan-**Animate** especificamente não aparece na lista de modelos suportados. [V: repositório do musubi-tuner]

### 5.5 Detalhamento e upscale da imagem-guia
- Detailer de rosto e mãos (Impact Pack), custom node; ou inpaint manual com o ControlNet de inpainting do MIC-Lab (nativo). [V]
- Upscale: 2× com modelo anime (AniScale 2, Span) via `UpscaleModelLoader` (nativo). [V]
- Fundo: gerar separado e compor; remover fundo com segmentação (SAM3 nativo aqui; BiRefNet [L]).

### 5.6 Quantos modelos, afinal
Imagem-guia: 1 base + 1 CN union (ou 2 CNs específicos) + 1 IP-Adapter (+ CLIP Vision) ou 1 LoRA + 1 detailer + 1 upscaler = **5 a 7**. Vídeo: 1 modelo 14B + text encoder + VAE 2.1 + clip_vision_h + 1 a 2 LoRAs (distill de 4 steps; DPO ou relight no SCAIL-2) + SAM3 (SCAIL) = **6 a 7**. Pós: RIFE + upscaler + denoise = **3**. Total de uma pipeline completa: **14 a 17 modelos**, contra os 3 que usávamos (base, openpose, canny).

---

## 6. O que mais é feito além disso (práticas, não modelos)
1. **Descrição do personagem por LLM** antes de gerar, no formato aparência/fundo, sem ação. [V: Wan-Animate-2]
2. **Duas passadas**: rascunho em 480p com LoRA de 4 steps para escolher seed e movimento; final em 720p com 20 steps. É o que o Comfy recomenda para VRAM e o que o nosso sweep mostrou ser necessário. [V + experiência]
3. **Driver limpo**: fundo neutro, câmera fixa, mesma direção de rosto que a referência. [V: Kling]
4. **Cache do ramo de pose** (`WanAnimate2Cache`): confirmado com citação literal do blog do Comfy — *"reuses the pose branch's work across sampling steps instead of recomputing it every step, roughly halving generation time in exchange for system memory"*. O custo é **RAM do sistema** (o nó default é `device=cpu` justamente porque o cache não cabe em VRAM junto do modelo). Mecanismo diferente e somável: `pose_end_percent` < 1 pula o ramo de pose fora da janela, o que também acelera. [V: blog Comfy + tooltips dos nós]
5. **Blocos com color match** para clipes longos. [V]
6. **Twos**: 12 desenhos por segundo em base 24; interpolar só quando o movimento pede (exp=2). [V/indício]
7. **Correção manual e propagação** (EbSynth 2, Krita) para o frame que a IA erra: 1 de 12 frames ruins é trabalho de 20 minutos de retoque, não de mais uma varredura. [V: ferramentas; [I]: economia]
8. **Varredura de seed com critério visual** (o que fizemos) continua sendo prática padrão; o que muda é a taxa de acerto por seed do modelo escolhido.

---

## 7. Plano recomendado para esta máquina, em ordem
1. **Driver**: gravar 5 s de caminhada lateral com celular (ou render MMD/Mixamo). Custo: minutos.
2. **Baixar** SCAIL-2 fp8 (ou o distill do Animate-2), mais clip_vision_h, VAE 2.1 e lightx2v: **17,69 + 1,26 + 0,25 + 0,74 = 19,95 GB**. O text encoder `umt5_xxl_fp8_e4m3fn_scaled` (6,3 GB) **já está em disco e é exatamente o que o Animate-2 pede** — não re-baixa. O VAE local é `wan2.2_vae` e **não serve**; precisa do Wan 2.1. `models/clip_vision/` está vazio. Sobra: 52 − 19,95 = **32,05 GB**. [V: `df` + tamanhos no HF]
3. **Smoke 480p / 4 steps**: medir s/frame. A parte "se carrega no ROCm" já está respondida — fp8_e4m3fn carrega aqui (o umt5 é fp8) e o int8 convrot foi medido correto na GPU (§3). O que **falta medir é velocidade**, não corretude.
4. **Referência**: luffy_h1_00001 como está; se o modelo falhar em roupa, fazer sheet de 3 vistas (Nano Banana Pro, centavos) e usar a frontal como `reference_image`.
5. **Gerar 81 frames**, 2 ciclos, escolher 12 do meio (ou 24 para twos), gates e contagem de pés.
6. **Pós** com TheAnimeScripter (DirectML/AMD): dedup, upscale anime 2×, FastLineDarken.
7. Se a identidade ainda oscilar: LoRA do personagem no Wan (seção 5.4), verificando antes musubi-tuner em ROCm.

Bifurcação paga: se a GPU não carregar 14B, Kling 3.0 Motion Control com o mesmo driver e a mesma referência custa menos de US$ 1 por tentativa e responde em minutos.

---

## 8. O que a validação de 06–07/09/2026 achou

**Denominador: 60 afirmações deste guia foram conferidas contra a fonte.** 51 confirmadas, 6 erradas, 2 imprecisas, 1 pendente. (51+6+2+1 = 60.) Método: instalação real em `C:\rk\ComfyUI`, tamanhos exatos em bytes lidos do HF, READMEs oficiais, e uma medição na própria GPU com controle negativo.

### 8.1 As 6 que estavam erradas (já corrigidas acima)
| # | O que o guia dizia | O que a fonte diz |
| --- | --- | --- |
| 1 | "Wan-Animate, 77 por extensão" | 77 é o `length` default do `WanAnimateToVideo` **v1**; o Animate-2 usa 81 e a âncora é 5 |
| 2 | Seedance **2.5**: 9 imagens + 3 vídeos + 3 áudios | isso é o **2.0**; o 2.5 vai a 50 entradas (30 img, 10 vídeo, 10 áudio) |
| 3 | Kling: "vídeo de referência de 3 a 30 s [V: página oficial]" | **não consta** na página oficial citada |
| 4 | Kling: US$/s "[V: agregadores]" | oficial é **em créditos** (6/8 por s); USD/s é preço de revendedor |
| 5 | NoobAI-XL "13 M imagens" | **não consta** no README — e a licença **proíbe uso comercial, inclusive da imagem gerada** |
| 6 | "se o SCAIL-2 exigir SAM3.1… o Animate-2 é o caminho sem lacuna" | máscara SAM3 é `optional=True`; o checkpoint existe (2,83 GB). Premissa falsa |

**As 2 imprecisas:** RIFE "4.15 a 4.25" (é 4.6 a 4.25); Animagine "retreino do zero" (é retreino **a partir do SDXL 1.0**).

**O que ninguém tinha notado e o guia agora tem:** Wan-Animate-2 traz **controle de ponto de vista por texto** e uma variante **Lite** de tempo real; existe **distill oficial** (10 steps) além da LoRA lightx2v; o SCAIL-2 tem quantização **nvfp4 de 11 GB**; o conjunto alfa do Wan 2.1 são **três** arquivos, não um; a doc oficial do Anima não menciona IP-Adapter.

### 8.2 O que continua pendente (e o que cada uma decide)
| Pendência | Decide | Custo |
| --- | --- | --- |
| Velocidade do int8 sem triton | se vale trocar 1 GB de disco por risco de lentidão. Base de comparação agora existe: **11,67 s/frame** no fp8 a 81 frames | 1 comparação |
| Preços de Vidu e Seedance em página oficial | orçamento da bifurcação paga | 2 páginas |
| Veo 3.1 (3 refs), Wan 2.7 (grade de 9), Runway Act-Two | nada crítico; só o texto do §4 | 3 páginas |
| musubi-tuner em ROCm Windows | LoRA local vs nuvem. Hoje: **não documentado**, CUDA-first | 1 teste real |

**Continuam proibidos em decisão:** "94% vs 73%", "93%", "95%" — números de blog sem denominador publicado.

## 9. Fontes
- Comfy blog, Wan Animate 2: https://blog.comfy.org/p/wan-animate-2-is-now-available-in
- Docs Comfy, Wan2.2 Animate: https://docs.comfy.org/tutorials/video/wan/wan2-2-animate
- Docs Comfy, SCAIL-2: https://docs.comfy.org/tutorials/video/zai/scail2
- SCAIL-2 README (MIT, jun/2026): https://huggingface.co/zai-org/SCAIL-2 · pesos Comfy: https://huggingface.co/Comfy-Org/SCAIL-2
- Wan2.2-Animate-2 README: https://huggingface.co/Wan-AI/Wan2.2-Animate-2-14B · pesos Comfy: https://huggingface.co/Comfy-Org/Wan-Animate-2
- Kijai fp8 Animate v1: https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled
- LTX-2.5: https://huggingface.co/Lightricks/LTX-2.5 · https://comfy.org/ltx-2.5/
- Kling Motion Control (oficial): https://kling.ai/feature/ai-motion-control · relatório técnico: https://arxiv.org/html/2603.03160v1
- Runway Act-Two: https://help.runwayml.com/hc/en-us/articles/42311337895827-Performance-Capture-with-Act-Two
- Ranking anime 2026 (blog, indício): https://www.elser.ai/blog/best-ai-video-generator-for-anime-creators-in-2026-7-tools-tested-and-ranked
- Consistência 2026 (blog, indício): https://blog.neural4d.com/comparisons/best-ai-video-generator-for-consistent-characters/
- Preços (agregadores, indício): https://www.cometapi.com/seedance-2-5-api-pricing/ · https://www.buildmvpfast.com/api-costs/ai-video
- Wan 2.7 API-only: https://wan27.org/blog/wan-2-7-release-date-open-source
- Modelos anime 2026 (note.com): https://note.com/reocoffee/n/n8efb5707dfa2?hl=en
- Anima: https://docs.comfy.org/tutorials/image/anima/anima · https://lilting.ch/en/articles/anima-2b-anime-image-generation
- ControlNet union xinsir: https://huggingface.co/xinsir/controlnet-union-sdxl-1.0 · Illustrious CN: https://huggingface.co/MIC-Lab/illustriousXLv1.1_controlnet
- NoobAI CN: https://civitai.com/models/962537/noobai-xl-controlnet-openpose
- IP-Adapter 2026 (blog): https://digitalzoomstudio.net/2026/02/stable-diffusion-character-consistency/
- LoRA Wan 2.2 (guia): https://wan27.org/blog/wan-2-2-lora-training-guide · musubi: https://github.com/kohya-ss/musubi-tuner/discussions/455
- TheAnimeScripter: https://github.com/NevermindNilas/TheAnimeScripter
- EbSynth 2: https://www.cgchannel.com/2025/10/ebsynth-2-can-turn-video-into-animation-without-using-ai/
- Character sheets (blogs): https://selfielabstudio.com/blog/nano-banana-pro-consistent-character-sheets-guide-20260216 · https://selfielabstudio.com/blog/flux-2-pro-multi-reference-character-sheets-guide-20260307
- MikuDance (paper): https://arxiv.org/html/2411.08656v1

**Acrescentadas na validação de 06–07/09/2026:**
- SCAIL-2, paper: https://arxiv.org/abs/2606.10804 · Wan-Animate-2, paper: https://arxiv.org/pdf/2608.06009
- Checkpoint SAM3D-Body: https://huggingface.co/Comfy-Org/sam-3d-body
- VAE alfa do Wan 2.1: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged (`split_files/vae/wan_alpha_2.1_*`)
- NoobAI-XL 1.1 (licença com proibição comercial): https://huggingface.co/Laxhar/noobai-XL-1.1
- Animagine XL 4.0 (8,4 M): https://huggingface.co/cagliostrolab/animagine-xl-4.0
- IP-Adapter FaceID SDXL + LoRA: https://huggingface.co/h94/IP-Adapter-FaceID
- Seedance 2.5, anúncio oficial: https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5
- Evidência local: `comfy_extras/nodes_wan.py`, `nodes_scail.py`, `comfy/quant_ops.py` na instalação `C:\rk\ComfyUI` (0.34.0, commit `6e3c0bd`)
