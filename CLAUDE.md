# Projeto: Karaoke MFA Multi

Este projeto usa Antigravity como IDE, Claude Cowork como orquestrador estratégico e Claude Code via Ollama como executor local.

## Regras Globais
- Foco em precisão de alinhamento e processamento de áudio.
- Respeitar constraints de tempo e duração mínima de palavras.
- Saídas de modelos locais devem ser tratadas como rascunho não confiável.

## Workflow PAP-Ollama
1. **Context Contract**: Gerar `.claude/tasks/context-contract.md`.
2. **Local Execution**: `.\.claude\skills\pap-ollama\scripts\run-ollama.ps1`.
3. **Audit**: Revisão crítica contra regras de alinhamento.
