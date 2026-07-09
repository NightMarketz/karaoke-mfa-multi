# Spec do Projeto: Karaoke MFA Multi

Documentação de especificação do projeto, preservando os contratos centrais: app local Flask, pipeline file-based, etapas `s03b–s08`, Review Wizard, geração ASS com `\kf`, render MP4 via ffmpeg, manifests, provenance e export gate.

## Estrutura

```txt
/spec
  PRD.md
  PROJECT_CONSTITUTION.md
  SDD.md
  GRAPHS.md
  ADR/
    ADR-001-file-based-architecture.md
    ADR-002-lyrics-first-mvp.md
    ADR-003-review-gated-export.md
    ADR-004-versioned-style-library.md
    ADR-005-provenance-manifests.md
    ADR-006-single-heavy-job.md
    ADR-007-candidate-take.md
  AGENTS.md
  TASK_SPEC_TEMPLATE.md
  DEFINITION_OF_DONE.md
  RBAC_MATRIX.md
  DATA_DICTIONARY.md
  STATE_MACHINES.md
  TEST_PLAN.md
```

## Ordem recomendada para reconstrução

### Fase 1 — Contratos de base
1. Criar `jobs/{job_id}`.
2. Implementar `meta.json`.
3. Implementar `status.json`.
4. Implementar safe paths.
5. Implementar `events.jsonl`.
6. Criar testes de job lifecycle.

### Fase 2 — Upload
1. Formulário básico.
2. ZIP seguro.
3. Stems separados.
4. Validação de letra obrigatória.
5. Validação de preset.
6. Conversão para WAV padrão.

### Fase 3 — Pipeline mínimo
1. `s03b` ou alinhador equivalente escrevendo `transcript.json`.
2. `s04` com fallback e floor de 50 ms.
3. `s05` determinístico para forced alignment.
4. `s06` gerando ASS com `\kf`.
5. `s07` renderizando MP4.
6. `s08` validando contratos.

### Fase 4 — Provenance e export gate
1. Manifest do ASS.
2. Manifest do MP4.
3. Hash validation.
4. Artifact graph.
5. Download bloqueado por gate.

### Fase 5 — Review Wizard
1. Criar `review_wizard.json`.
2. Gerar issues.
3. Quality report.
4. Review points.
5. Preview approval.
6. Full preview.
7. Export com risco aprovado.

### Fase 6 — UI
1. Cockpit simples.
2. Job detail.
3. Review Wizard funcional.
4. Timeline avançada somente depois.
5. Editor visual somente depois.

## Checklist final de aceite da spec

- [ ] PRD define problema, escopo, usuários, requisitos e métricas.
- [ ] Constitution congela princípios e invariantes.
- [ ] SDD define arquitetura, pipeline, rotas e segurança.
- [ ] Graphs mostram contexto, pipeline, artifact graph e Review Wizard.
- [ ] ADRs registram decisões técnicas principais.
- [ ] Agents têm responsabilidades, inputs e outputs.
- [ ] Task template permite implementar fatias sem perder contratos.
- [ ] Definition of Done bloqueia entregas incompletas.
- [ ] RBAC modela permissões mesmo sem auth no MVP.
- [ ] Data Dictionary define artefatos JSON.
- [ ] State Machines formalizam job, review, export e issues.
- [ ] Test Plan cobre contratos, segurança, integração e revisão.
