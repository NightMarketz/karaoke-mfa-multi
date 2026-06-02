# Projeto: Karaoke MFA Multi

Este projeto usa Antigravity como IDE, Codex Cowork como orquestrador estratégico e Codex via Ollama como executor local.

## Regras Globais
- Foco em precisão de alinhamento e processamento de áudio.
- Respeitar constraints de tempo e duração mínima de palavras.
- Saídas de modelos locais devem ser tratadas como rascunho não confiável.

## Workflow PAP-Ollama
1. **Context Contract**: Gerar `.Codex/tasks/context-contract.md`.
2. **Local Execution**: `.\.Codex\skills\pap-ollama\scripts\run-ollama.ps1`.
3. **Audit**: Revisão crítica contra regras de alinhamento.

## Skill Routing
- Antes de tarefas estruturais, consultar `docs/skills/routing.md`.
- Hardcodes, configuracao, paths, modelos, host/port e thresholds: usar `hardcoded-config-audit` quando a skill existir.
- Mudancas em estagios `s01`-`s08`, artefatos, manifests ou orquestracao: usar `pipeline-stage-contracts` quando a skill existir.
- Timing, alinhamento, duracao minima, drift, gaps, melisma, sustain ou fallback: usar `audio-alignment-audit` quando a skill existir.
