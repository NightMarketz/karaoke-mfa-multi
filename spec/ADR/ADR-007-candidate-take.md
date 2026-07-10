# ADR-007 — Candidate take

**Status:** Aceito

## Contexto
Uma correção de timing agressiva pode melhorar ou piorar. Sobrescrever a versão
aprovada silenciosamente destrói trabalho bom e some com o histórico.

## Decisão
Correção arriscada/agressiva gera um **candidate take** — uma versão alternativa
— em vez de sobrescrever a take aprovada. A troca é uma decisão auditada, nunca
automática e silenciosa.

## Consequências
- ✅ Take aprovada nunca é perdida; comparar candidato × aprovado é possível.
- ✅ Casa com a política de evidência (Constituição §4) e com o versionamento de edições.
- ⚠️ Exige rastrear takes e sua proveniência (`tests/test_review_wizard_versioning.py`).

Ver [../PROJECT_CONSTITUTION.md](../PROJECT_CONSTITUTION.md) §4 e [../STATE_MACHINES.md](../STATE_MACHINES.md).
