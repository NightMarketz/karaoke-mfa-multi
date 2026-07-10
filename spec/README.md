# Especificação — Karaoke MFA Multi

Fonte canônica de verdade da **intenção** do projeto. O código é a verdade da
**implementação**; quando esta spec divergir do código, o código vence e a spec
é corrigida.

Ferramenta **local** (não-SaaS) em Flask que converte *stems* de música + letra
em um **MP4 de karaokê** com legenda ASS embutida e destaque por palavra (`\kf`).

## Como ler

Ordem sugerida para quem chega agora:

1. [PRD.md](PRD.md) — o que o produto é, escopo do MVP, usuários, requisitos funcionais.
2. [PROJECT_CONSTITUTION.md](PROJECT_CONSTITUTION.md) — os invariantes inegociáveis (contratos de artefato, valores de timing, ações proibidas).
3. [SDD.md](SDD.md) — arquitetura, pipeline `s01–s08`, tabela **completa** de rotas HTTP, plano de execução web.
4. [GRAPHS.md](GRAPHS.md) — diagramas (pipeline, máquinas de estado, export gate).
5. [ADR/](ADR/) — decisões de arquitetura registradas (001–007).

Referência:

- [DATA_DICTIONARY.md](DATA_DICTIONARY.md) — schema de cada artefato, ligado aos *contract tests* que o fixam.
- [STATE_MACHINES.md](STATE_MACHINES.md) — ciclo de vida do job, do Review Wizard, do export gate e das issues.
- [RBAC_MATRIX.md](RBAC_MATRIX.md) — papéis lógicos (não há autenticação real no MVP).
- [AGENTS.md](AGENTS.md) — os agentes lógicos do pipeline e seus contratos.
- [TEST_PLAN.md](TEST_PLAN.md) — o que a suíte cobre e como rodá-la.
- [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md) — o portão global antes de considerar algo pronto.
- [TASK_SPEC_TEMPLATE.md](TASK_SPEC_TEMPLATE.md) — molde para especificar uma nova fatia de trabalho.

## `spec/` × `docs/`

Sem duplicação: `spec/` descreve **o que deve ser verdade e por quê**; `docs/`
descreve **como operar** (rodar, resolver problemas, quais skills existem). Onde
os dois se tocam, `docs/` linka para `spec/` em vez de repetir.

- [../docs/README.md](../docs/README.md) — ponto de entrada operacional.
- [../docs/architecture/README.md](../docs/architecture/README.md) — visão de arquitetura (resumo; detalhe em [SDD.md](SDD.md)).
- [../docs/TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) — problemas comuns.
- [../docs/skills/README.md](../docs/skills/README.md) — skills existentes e adiadas.

## Ordem de reconstrução

Se o projeto for reconstruído do zero, esta é a ordem que respeita os contratos:

1. **Contratos-base** — diretório do job, `meta.json`/`status.json`/`events.jsonl`, caminhos seguros, testes de ciclo de vida.
2. **Upload** — ZIP Suno ou stems separados → normalização para WAV.
3. **Pipeline mínimo** — `s03b → s04 → s05 → s06 → s07 → s08`.
4. **Proveniência + export gate** — manifests SHA-256, bloqueio de download.
5. **Review Wizard** — issues, preview, aprovação, risco.
6. **UI** — cockpit primeiro; timeline/editor visual por último.
