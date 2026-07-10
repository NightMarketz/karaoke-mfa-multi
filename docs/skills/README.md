# Skills do projeto

Skills locais no formato SDD (spec-first, não TDD). Cada skill tem regra de
domínio + passo de **verificação executável**. Use [routing.md](routing.md) para
decidir quando cada uma se aplica.

## Superfícies

- **`.claude/skills/`** — canônica para Claude Code (esta sessão).
- **`.Codex/skills/`** — mirror para Codex, conteúdo idêntico (referenciado por [`../../AGENTS.md`](../../AGENTS.md)).

Os dois hosts leem diretórios diferentes, então a duplicação é da plataforma;
mantenha as duas cópias iguais ao editar.

## Active Project Skills (skills ativas — 4)

| Skill | Quando | Verificação |
|---|---|---|
| `pap-ollama` | Geração local via Ollama (Plan-Audit-Patch). Manual (`disable-model-invocation`). | suíte verde; draft nunca aplicado sem auditoria |
| `hardcoded-config-audit` | Mudar path/model/host/porta/timeout/threshold hardcoded ou centralizar config. | `test_app_config` + suíte |
| `audio-alignment-audit` | Mudar constante de timing/alinhamento (min_dur, MIN_WORD_MS, snap, preroll/postroll/gap, melisma). | `test_audio_alignment_contracts.py` |
| `pipeline-stage-contracts` | Mudar artefato/schema/ordem de estágio (transcript/aligned/analysis/ass/manifest). | `test_pipeline_stage_contracts.py` |

## Skills adiadas (rubric não atingido *ainda*)

Só vira skill o que **recorre + tem regra de domínio com julgamento + tem
verificação executável**. Estas ficam adiadas até haver recorrência real; por ora
a regra vive na spec:

- **`review-wizard-qa`** — fluxo do Review Wizard (points, issues, preview, export gate). Regra já capturada em [../../spec/STATE_MACHINES.md](../../spec/STATE_MACHINES.md); vira skill quando o QA do wizard recorrer como tarefa.
- **`karaoke-style-library`** — presets/seção→estilo/efeitos. Regra em [ADR-004](../../spec/ADR/ADR-004-versioned-style-library.md); `test_karaoke_style_library.py` já protege. Skill só se edições de estilo virarem frequentes.
- **`provenance-artifact-audit`** — manifests/hash/reuso. Coberto por `pipeline-stage-contracts` + `test_provenance_contracts.py`; não minta skill separada sem necessidade recorrente.

## Regra de criação

Não crie skill porque um workflow se repetiu uma vez. Crie só quando houver
trabalho recorrente, regra clara de projeto e critério de verificação testável
(ver [gap-analysis.md](gap-analysis.md) e [../../spec/TASK_SPEC_TEMPLATE.md](../../spec/TASK_SPEC_TEMPLATE.md)).
