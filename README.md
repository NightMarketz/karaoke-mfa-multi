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

Tempo: `~Xs` — **ainda não medido nesta máquina**. A AMD divulga <30s para
Z-Image Turbo nesta família de processador, mas isso é alegação de terceiro
sobre outro hardware, não medição local. Substituir por um número real na
primeira execução.

> **Este caminho nunca foi executado contra um ComfyUI real.** Nenhum job
> completou neste repositório até agora: a primeira execução é também a
> primeira validação. Tudo que existe hoje são testes unitários com HTTP
> dublado.

#### Exportou seu próprio workflow do ComfyUI? Confira dois valores

Ao substituir `config/comfy_workflow.json` por um export próprio (formato
**API**), dois valores em `karaoke/background.py` têm de bater com a sua
instância — os dois estão lá como constante no topo do arquivo:

| constante | valor hoje | o que acontece se estiver errado |
|---|---|---|
| `COMFY_PROMPT_NODE` | `"6"` | id do nó `CLIPTextEncode` **positivo** no seu export. Outro id → `KeyError` a cada job, capturado pelo `except` do estágio: fallback silencioso e permanente para o fundo chapado. |
| porta em `COMFY_HOST` | `8188` | porta HTTP do ComfyUI. **Não verificada** contra o ComfyUI Desktop desta máquina. Porta errada → conexão recusada, mesmo fallback silencioso. |

Nos dois casos o job termina normalmente e o vídeo sai — sem ilustração. O
único sinal é a linha `AVISO: fundo nao gerado (...)` no log do estágio 11.

### 🖼️ Pré-requisitos para rodar um job real ponta a ponta

Além dos requisitos gerais de instalação, um job completo (que passa pelo
Estágio 11 gerando ilustração de verdade, em vez de cair no fundo chapado
`#08090f`) precisa de:
1. ComfyUI Desktop aberto, com `config/comfy_workflow.json` exportado em
   formato API.
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
