# Multilingual Karaoke Pipeline (New Way 2025)

Sistema avançado de alinhamento e geração de vídeos de Karaoke, utilizando uma arquitetura baseada em **Jobs** e alinhamento de alta fidelidade (**CTC + Onset DTW**).

## 🚀 Arquitetura "New Way"

Este repositório foi modernizado para seguir o padrão de 2025:
- **Isolamento por Job**: Todos os arquivos gerados são armazenados em `work/jobs/{job_id}/`.
- **Pipeline de 13 Estágios**: Desde o preprocessamento até a renderização final do vídeo.
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

1.  **Audio Preprocessing**: Normalização e conversão inicial.
2.  **Vocal Separation**: Extração vocal via Demucs.
3.  **Corpus Prep**: Preparação dos arquivos `.lab` e dicionário.
4.  **CTC Align**: Alinhamento fonético inicial.
5.  **WhisperX Rescue**: Recuperação de segmentos não alinhados.
6.  **Gemini Adlibs**: Identificação de partes extras via LLM.
7.  **VAD Clamping**: Ajuste de silêncios e limites vocais.
8.  **Onset DTW**: Sincronização milimétrica baseada em transientes de áudio.
9.  **Background Illustration**: ilustração de fundo gerada localmente a partir
    da letra (Ollama `llama3.2:3b` → ComfyUI `z_image_turbo`). Requer os dois
    serviços de pé; sem eles o vídeo sai com fundo chapado. Tempo: `~Xs`
    — ainda não medido nesta máquina; a AMD divulga <30s para Z-Image Turbo
    nesta família de processador, mas isso é alegação de terceiro sobre outro
    hardware, não medição local. Substituir por um número real na primeira
    execução.
10. **ASS Conversion**: Geração da legenda Karaoke (.ass).
11. **QC Report**: Relatório de qualidade automático.
12. **Audio Mixing**: Mixagem final (Vocal + Instrumental).
13. **Video Render**: Renderização final do vídeo para Karaoke.

### 🖼️ Pré-requisitos para rodar um job real ponta a ponta

Além dos requisitos gerais de instalação, um job completo (que passa pelo
Estágio 9 gerando ilustração de verdade, em vez de cair no fundo chapado
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
sobre o fundo e o fundo pulsa na batida.

## 📁 Estrutura de Pastas
- `karaoke/`: Biblioteca core de lógica e processamento.
- `scripts/`: Scripts individuais de cada estágio (01-09).
- `web/`: Frontend da aplicação (se disponível).
- `work/jobs/`: Onde a "mágica" acontece (logs, temporários, finais).

---
*Mantido por Andru.ia Modernization Engine.*
