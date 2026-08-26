# Multilingual Karaoke Pipeline (New Way 2025)

Sistema avançado de alinhamento e geração de vídeos de Karaoke, utilizando uma arquitetura baseada em **Jobs** e alinhamento de alta fidelidade (**CTC + Onset DTW**).

## 🚀 Arquitetura "New Way"

Este repositório foi modernizado para seguir o padrão de 2025:
- **Isolamento por Job**: Todos os arquivos gerados são armazenados em `work/jobs/{job_id}/`.
- **Pipeline de 14 Estágios por execução**: do preprocessamento à renderização final.
  (`run_pipeline.py` registra 17 invocações de script: 14 rodam em cada execução,
  porque os estágios 4–6 têm duas variantes mutuamente exclusivas — MFA ou
  SOFA/ROSVOT. Os `id` dos estágios vão de 1 a 14.)
- **Resiliência**: Suporte nativo a resume via `resume_planner.py`.
- **Diferenciais**:
    - Alinhamento CTC (Forced Alignment).
    - WhisperX Rescue para letras difíceis.
    - Detecção de Adlibs via Gemini.
    - Ajuste fino via Onset DTW.

## 🛠️ Instalação

### Requisitos
- **Python 3.10+** (Conda recomendado).
- **FFmpeg** instalado e no PATH.
- **Micro-Mamba/Conda** para gerenciamento de envs.

### Setup
Execute o script de inicialização para criar os ambientes necessários:
```powershell
./setup_envs.ps1
```

## 📖 Como Usar

### Interface de Linha de Comando (CLI)
Para processar uma música manualmente:
```bash
python run_pipeline.py --audio "path/to/song.mp3" --lyrics "path/to/lyrics.txt" --lang "pt"
```

**Resumar um Job falho:**
```bash
python run_pipeline.py --job-id "job_123456" --resume
```

### Servidor Web (Andru.ia)
Para rodar o backend da aplicação:
```bash
python server.py
```

## 📋 Estágios do Pipeline

Derivado de `run_pipeline.py` (é ele quem define a verdade; a lista abaixo
segue a ordem e os nomes que ele registra). 14 estágios por execução.

| # | Estágio | Script |
|---|---|---|
| 1 | Media Prep | `01_media_prep.py` |
| 2 | Vocal Isolation | `02_vocal_isolation.py` |
| 3 | Vocal Cleaning | `03_vocal_cleaning.py` |
| 4–6 | **Caminho MFA** (padrão) | `03_prepare_corpus.py`, `04_mfa_alignment.py`, `05_mfa_to_json.py` |
| 4–6 | **Caminho SOFA/ROSVOT** (`--aligner sofa`) | `03_forced_align_sofa.py`, `03b_rosvot_inference.py`, `fuse_sofa_rosvot.py` |
| 7 | Gap Analysis & Sync | `05_gap_analysis.py` |
| 8 | Alignment Rescue | `06_alignment_rescue.py` |
| 9 | Gemini Alignment | `07_gemini_alignment.py` |
| 10 | Onset DTW | `08_onset_dtw.py` |
| 11 | Background Illustration | `08b_background_image.py` |
| 12 | Video Rendering | `09_video_rendering.py` |
| 13 | System Cleanup | `11_system_cleanup.py` |
| 14 | Process Conclusion | `13_process_conclusion.py` |

O `server.py` monta uma lista **parecida, mas não igual** (e renumera os `id`
no fim de `_build_steps`): também 14 estágios no caminho MFA, mas com um só
estágio de MFA (`04_mfa_alignment.py`, sem `03_prepare_corpus.py` nem
`05_mfa_to_json.py`) e dois estágios a mais no fim (`10_quality_assurance.py`
e `12_user_notification.py`). Com `--aligner sofa` são 16 — e dois dos
scripts que ele invoca nesse caminho (`run_sofa.py`, `run_rosvot.py`) não
existem no repositório.

### Estágio 11 — Background Illustration

Ilustração de fundo gerada localmente a partir da letra (Ollama `llama3.2:3b`
escreve o brief → ComfyUI `z_image_turbo` gera a imagem). Requer os dois
serviços de pé; sem eles o estágio avisa, sai 0, e o vídeo sai com fundo
chapado `#08090f`. A letra crua nunca vai para o gerador de imagem — só o
brief escrito pelo LLM.

Tempo **medido nesta máquina** (ROG Flow Z13, Radeon 8060S, ComfyUI 0.18.5 com
ROCm reportando 99,7 GB de VRAM unificada), job real da música "Publi":

| execução | tempo |
|---|---|
| 1ª (a frio, carregando o modelo de 6B) | **57 s** |
| seguinte (modelo quente) | **19 s** |
| com PNG já em cache | **0 s** |

A AMD divulga <30 s para Z-Image Turbo nesta família; com o modelo quente bate,
a frio não. O brief do Ollama são ~5 s desse total.

> **Executado contra um ComfyUI real em 2026-08-25** (música "Publi"): gera,
> salva, o cache pula e o nonce anti-cache funciona — a 2ª geração devolveu
> imagem diferente, não `execution_cached` com saída vazia.
>
> **O elo fraco é o brief, não a imagem.** Em 2 gerações, 2 respeitaram "sem
> texto na imagem" e **1 respeitou "centro escuro"** — medindo a luminância da
> faixa onde a legenda cai: 36/255 na boa, 115/255 (pico 243) na ruim, onde
> legenda branca briga com o fundo. As regras de `IMAGE_RULES` vão coladas no
> fim do prompt, mas o conteúdo do brief vence: pedir "cidade iluminada por luz
> branca" clareia o centro apesar da regra.
>
> Além disso o `llama3.2:3b` **responde em português** quando a letra é em
> português, apesar do system prompt pedir inglês — e Z-Image é treinado em
> inglês. Duas melhorias óbvias e ainda não feitas: forçar o idioma do brief e
> restringir a composição (ex.: exigir que o terço inferior fique escuro).

#### O workflow que vem no repo, e de onde ele saiu

`config/comfy_workflow.json` **já existe**, derivado do template canônico
`image_z_image_turbo.json` que o próprio ComfyUI instala em
`.venv/Lib/site-packages/comfyui_workflow_templates_json/templates/`. Não foi
escrito de memória: o template é um subgraph em formato UI, e o grafo abaixo
saiu de expandir `definitions.subgraphs` e ler os 18 links um a um.

| nó | valor | por quê |
|---|---|---|
| `UNETLoader` | `z_image_turbo_bf16.safetensors` | Apache-2.0, 8 passos |
| `CLIPLoader` | `qwen_3_4b.safetensors`, tipo **`lumina2`** | o tipo não é adivinhável; vem do template |
| `VAELoader` | `ae.safetensors` | idem |
| `EmptySD3LatentImage` | 1024×576 | 16:9, lado maior ≤ 1024 |
| `KSampler` | 8 passos, cfg 1, `res_multistep`/`simple` | valores do template turbo |
| `ConditioningZeroOut` | negativo | o template não usa prompt negativo |

Verificado estaticamente: os três arquivos de modelo existem em
`C:/ComfyUI/models/`, todo link aponta para nó existente, o template parseia
depois da substituição e o `_bust_cache` encontra o `filename_prefix`.
**E verificado em execução:** este grafo foi submetido ao ComfyUI 0.18.5 real e
produziu imagem em 19 s com o modelo quente (ver medições acima). O tipo
`lumina2` e o `EmptySD3LatentImage` — os dois valores que um chute erraria —
foram confirmados na prática.

Se você trocar por um workflow seu, o export cru da GUI **não** funciona.
Depois de **Workflow → Export (API)**, edite o arquivo e troque dois valores
por marcadores literais:

| no export | vira | onde |
|---|---|---|
| `"text": "beautiful scenery"` | `"text": "%prompt%"` | o nó `CLIPTextEncode` **positivo** |
| `"seed": 123456789` | `"seed": %seed%` | o `KSampler` |

Repare que `%prompt%` fica **entre aspas** (o código escapa o brief e o insere
no lugar do marcador) e `%seed%` fica **sem aspas** — é um número cru, e por
isso o arquivo com marcadores não é JSON válido até a substituição. É o
esperado.

O código nunca adivinha o id de um nó: os ids mudam a cada reexport da GUI, e
foi exatamente esse chute que o marcador substitui. Um export cru, sem editar,
levanta `o template do workflow tem de conter o marcador %prompt%` — falha
explícita, de propósito: renderizar o texto de placeholder em silêncio geraria
uma imagem errada sem nenhum aviso.

Uma seed nova é sorteada a cada chamada, e todo `filename_prefix` do grafo
recebe um sufixo único antes do envio. Sem isso o ComfyUI responde
`execution_cached` com `outputs: {}` ao reenviar um grafo idêntico — a mesma
música renderizada duas vezes perderia a ilustração, em silêncio e para sempre.

#### Vídeo animado (WAN 2.2): medido e descartado

Tentativa registrada para não ser repetida. O fundo animado em loop foi gerado
com WAN 2.2 i2v pelo `WanFirstLastFrameToVideo`, alimentando a **mesma imagem**
em `start_image` e `end_image` — a técnica que fecha o loop por construção.

Medido nesta máquina, cena 1 da "Publi", 832×480, 81 frames, 4 passos com a
LoRA LightX2V:

| | |
|---|---|
| tempo | **23,5 min** (17,4 s por frame) |
| emenda do loop | 2,39/255 contra 14,26/255 do controle — **fecha** |
| movimento | rampa global de brilho, pico de 63/255 |

**A técnica funciona; o custo e o resultado não compensam.** A LoRA de 4 passos
quase não acelerou (a AMD alega ~27 min com 20 passos) porque o gargalo é o VAE
sobre 81 frames, não a amostragem. E o movimento que saiu não é ambiente: o
quarto clareia e escurece, o que faz a faixa da legenda "respirar" a cada 5 s.

Para 6 cenas seriam ~2,35 h por música. O Ken Burns e o pulso nos onsets, que já
existem no Estágio 12, dão movimento por **zero** segundo de geração e mexem só
na posição, nunca no brilho.

#### Porta do ComfyUI: descoberta, não fixa

A porta não é confiável — o app já subiu em `8000`, `8001` e `8188` em sessões
diferentes. `karaoke/background.py` resolve o endereço na hora da chamada:

1. `COMFYUI_URL` no ambiente, se setada → usada literal, sem sondagem
   (ex.: `set COMFYUI_URL=http://127.0.0.1:8000`);
2. senão, sonda `8188`, `8000`, `8001` nessa ordem contra `/system_stats`
   (1,5 s cada) e usa a primeira que responder;
3. nenhuma responde → erro nomeando as três, e o log do estágio 11 diz onde
   procurou em vez de exibir um "conexão recusada" apontando só a primeira.

Em qualquer falha o job termina normalmente e o vídeo sai — sem ilustração. O
único sinal é a linha `AVISO: fundo nao gerado (...)` no log do estágio 11;
quando o ComfyUI responde sucesso mas sem imagem, essa linha agora carrega o
que o `/history` reclamou (o `status` e as `messages`), não só "sem imagem".

### 🖼️ Pré-requisitos para rodar um job real ponta a ponta

Além dos requisitos gerais de instalação, um job completo (que passa pelo
Estágio 11 gerando ilustração de verdade, em vez de cair no fundo chapado
`#08090f`) precisa de:
1. ComfyUI Desktop aberto. O `config/comfy_workflow.json` já vem no repo,
   derivado do template canônico (ver acima); só troque se quiser outro
   modelo, e aí marque com `%prompt%`/`%seed%`. Porta qualquer: é
   descoberta, ou fixada em `COMFYUI_URL`.
2. Ollama de pé, com `llama3.2:3b` puxado.
3. `GEMINI_API_KEY` no ambiente.
4. Entrada em `input/jobs/{id}/` com `song.mp3` e `lyrics.txt` — ou
   `input/test_1min/` para um snippet de 1 minuto, caminho barato para a
   primeira validação.

O que conferir depois de rodar: `08_background/background.png` existe e não
tem texto na imagem; o log do estágio de render diz `Fundo: ilustracao` e
`Bounce: N onsets` com N > 0; o MP4 sai; e, abrindo, a letra está legível
sobre o fundo, o fundo pulsa na batida e deriva devagar (Ken Burns) ao
longo da música.

## 📁 Estrutura de Pastas
- `karaoke/`: Biblioteca core de lógica e processamento.
- `scripts/`: Scripts individuais de cada estágio (`01_media_prep.py` a
  `13_process_conclusion.py`, incluindo os variantes `03b`/`08b` e os
  scripts do caminho SOFA sem prefixo numérico).
- `web/`: Frontend da aplicação (se disponível).
- `work/jobs/`: Onde a "mágica" acontece (logs, temporários, finais).

---
*Mantido por Andru.ia Modernization Engine.*
