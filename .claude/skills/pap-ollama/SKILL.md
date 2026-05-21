---
description: Workflow PAP local: Claude planeja, Ollama gera código, Claude audita e aplica patch mínimo. Use quando o usuário pedir geração local com Ollama, economia de tokens, ou integração Claude Code + Ollama.
disable-model-invocation: true
---

# PAP-Ollama Workflow

Você é o arquiteto e auditor do fluxo PAP-Ollama para o projeto Karaoke.

## Etapa 1 — Domain Context Discovery
Gerar `.claude/tasks/context-contract.md` com foco em processamento de áudio e alinhamento MFA.

## Etapa 2 — Prompt para Ollama
Gerar `.claude/tasks/current-prompt.md`.

## Etapa 3 — Espera
`.\.claude\skills\pap-ollama\scripts\run-ollama.ps1`

## Etapa 4 — Auditoria e Aplicação
Revisar contra `context-contract.md` e aplicar patch mínimo.
