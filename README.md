# Multilingual Karaoke Pipeline (New Way 2025)

Sistema avançado de alinhamento e geração de vídeos de Karaoke, utilizando uma arquitetura baseada em **Jobs** e alinhamento de alta fidelidade (**CTC + Onset DTW**).

## 🚀 Arquitetura "New Way"

Este repositório foi modernizado para seguir o padrão de 2025:
- **Isolamento por Job**: Todos os arquivos gerados são armazenados em `work/jobs/{job_id}/`.
- **Pipeline de 12 Estágios**: Desde o preprocessamento até a renderização final do vídeo.
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
9.  **ASS Conversion**: Geração da legenda Karaoke (.ass).
10. **QC Report**: Relatório de qualidade automático.
11. **Audio Mixing**: Mixagem final (Vocal + Instrumental).
12. **Video Render**: Renderização final do vídeo para Karaoke.

## 📁 Estrutura de Pastas
- `karaoke/`: Biblioteca core de lógica e processamento.
- `scripts/`: Scripts individuais de cada estágio (01-09).
- `web/`: Frontend da aplicação (se disponível).
- `work/jobs/`: Onde a "mágica" acontece (logs, temporários, finais).

---
*Mantido por Andru.ia Modernization Engine.*
