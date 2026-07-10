# Karaoke MFA Multi — Operação

Ferramenta **local** em Flask: stems de música + letra → MP4 de karaokê com
legenda ASS (`\kf`) embutida. Esta pasta é a camada **operacional**. A
especificação (o quê e por quê) está em [`../spec/`](../spec/README.md).

## Rodar

```bash
python server.py
```

Sobe em `http://localhost:5000` (config em `pipeline.toml [server]`). Abra `/`
(cockpit) → `/job/new` para enviar um job.

Um job precisa de: **letra** (`lyrics_text`, obrigatória no MVP) + os stems, seja
um **ZIP estilo Suno** ou uploads separados de **vocals** + **instrumental**.

## Pré-requisitos

- **ffmpeg** no PATH (normalização, demix e render).
- **Demucs** em ambiente próprio — o caminho do Python do demux é
  `pipeline.toml [demix].python` (**absoluto e específico da máquina**; ajuste
  para o seu). Ver [TROUBLESHOOTING](TROUBLESHOOTING.md).
- **Ollama** rodando (`localhost:11434`) só é necessário no caminho **sem letra**
  (`s05` analisa via Ollama); no caminho MVP (com letra) a análise é determinística.
- Checkpoint **HubertFA** em `models/hubertfa/model.onnx` para o `s04`.

## Fluxo

Pipeline `s01–s08` (detalhe em [../spec/SDD.md](../spec/SDD.md) §2). Caminho MVP:
`s03b → s04 → s05 → s06 → s07 → s08`. Ao final, o **Review Wizard**
(`/job/<id>/review`) trava o download até a qualidade ser aprovada (export gate).

## Testes

```bash
pytest tests
```

Detalhe (incl. a alternativa `unittest` e suas limitações) em
[../spec/TEST_PLAN.md](../spec/TEST_PLAN.md).

## Mapa

- Arquitetura: [architecture/README.md](architecture/README.md)
- Problemas comuns: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Skills: [skills/README.md](skills/README.md)
- Especificação completa: [../spec/README.md](../spec/README.md)

Regra permanente: saída de modelo local é sempre **rascunho não confiável** —
passa por contrato + evidência + testes antes de virar código ou artefato.
