# Skill Gap Analysis

Quais skills existem, quais faltam e a evidência exigida antes de criar uma nova.
A regra de criação (3 barras) está no [README.md](README.md).

## Active Project Skills (implementadas)

Passaram as 3 barras (recorrência + regra de domínio + verificação executável):

- `hardcoded-config-audit` — verificada por `test_app_config`.
- `pipeline-stage-contracts` — verificada por `test_pipeline_stage_contracts.py`.
- `audio-alignment-audit` — verificada por `test_audio_alignment_contracts.py`.
- `pap-ollama` — workflow manual Plan-Audit-Patch (ver [routing.md](routing.md)).

## Deferred candidates (adiadas)

Ainda não recorrem como tarefa própria; a regra já vive na spec e em testes de
contrato. Não crie até haver recorrência real:

- `review-wizard-qa` — QA do fluxo do Review Wizard. Regra em [../../spec/STATE_MACHINES.md](../../spec/STATE_MACHINES.md); já coberto por `test_review_wizard_*`.
- `karaoke-style-library` — presets/seção→estilo/efeitos. Regra em [../../spec/ADR/ADR-004-versioned-style-library.md](../../spec/ADR/ADR-004-versioned-style-library.md); coberto por `test_karaoke_style_library`.
- `provenance-artifact-audit` — manifests/hash/reuso. Coberto por `pipeline-stage-contracts` + `test_provenance_contracts`.
- `pap-ollama-audit` — a etapa de auditoria já é parte da skill `pap-ollama`; não minta skill separada.

## Evidence

Antes de promover um candidato a skill, junte a evidência:

- Quantas tarefas distintas invocariam a regra (recorrência).
- Qual regra de domínio com julgamento ela protege (não algo que um linter/CI resolve).
- Qual comando de teste prova o resultado (verificação executável).

## Priority

Ordem de promoção quando/se a recorrência aparecer:

1. `review-wizard-qa` (maior superfície de decisão perceptual).
2. `karaoke-style-library` (evita duplicar regra de seção/estilo).
3. `provenance-artifact-audit` (só se o reuso de artefato virar tarefa recorrente).
4. `pap-ollama-audit` (baixa — já embutida em `pap-ollama`).

## Creation Criteria

Só crie a skill quando as 3 barras forem atingidas ao mesmo tempo: recorrência
real, regra de domínio que exige julgamento, e um passo de verificação
executável. Caso contrário, mantenha a regra na spec ou num passo de tarefa (ver
[../../spec/TASK_SPEC_TEMPLATE.md](../../spec/TASK_SPEC_TEMPLATE.md)).
