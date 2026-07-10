# Tarefas

Artefatos de trabalho por tarefa (fluxo SDD/PAP), distintos da especificação
canônica em [../../spec/README.md](../../spec/README.md).

## Onde ficam

- **Contratos de contexto do PAP-Ollama**: gerados em `.claude/tasks/` (Claude Code) ou `.Codex/tasks/` (Codex) pela skill `pap-ollama` — `context-contract.md`, `current-prompt.md`, `current-output.md`. São regeneráveis por tarefa; não são fonte de verdade.
- **Molde de spec de tarefa**: [../../spec/TASK_SPEC_TEMPLATE.md](../../spec/TASK_SPEC_TEMPLATE.md).

## Regra

Toda tarefa que toca comportamento começa por um contrato de contexto +
evidência antes de editar código (ver [../skills/README.md](../skills/README.md)).
Saída de modelo local é rascunho não confiável até auditada.
