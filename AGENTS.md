# Projeto: Karaoke MFA Multi

Antigravity como IDE, Codex Cowork como orquestrador estratégico e Codex via
Ollama como executor local.

Ferramenta **local** em Flask: stems + letra → MP4 de karaokê com ASS `\kf`.
Especificação canônica em [`spec/`](spec/README.md); operação em
[`docs/`](docs/README.md). Este arquivo é o gêmeo Codex do
[`CLAUDE.md`](CLAUDE.md) — mesmas regras, superfície `.Codex/`.

## Regras Globais
- Foco em precisão de alinhamento e processamento de áudio.
- Respeitar constraints de tempo e duração mínima de palavras.
- **Saídas de modelos locais são rascunho não confiável** — passam por contrato + evidência + testes antes de virar código ou artefato (vale inclusive para a análise via Ollama do `s05`).

## Workflow PAP-Ollama
1. **Context Contract**: gerar `.Codex/tasks/context-contract.md`.
2. **Local Execution**: `.\.Codex\skills\pap-ollama\scripts\run-ollama.ps1`.
3. **Audit**: revisão crítica contra o context contract; aplicar patch mínimo.

Ver a skill [`.Codex/skills/pap-ollama/SKILL.md`](.Codex/skills/pap-ollama/SKILL.md).

## Skill Routing
Antes de tarefa estrutural, consultar [`docs/skills/routing.md`](docs/skills/routing.md).
Skills ativas (existem): `hardcoded-config-audit`, `pipeline-stage-contracts`,
`audio-alignment-audit`, `pap-ollama`.

## Constraints de alinhamento (load-bearing)
Os valores de timing são fixados em código e no snapshot
`tests/test_audio_alignment_contracts.py`. **Ao mudar qualquer valor, atualize
esse teste no mesmo commit.** A tabela completa (com file:line) está em
[spec/PROJECT_CONSTITUTION.md](spec/PROJECT_CONSTITUTION.md) §3 — não duplicar aqui.

Resumo: `min_dur` 50ms (s03b/s04) · `MIN_WORD_MS` 80ms (s06) ·
`validation.min_duration` 1ms (s08) · overlap 0.05s · `--snap-window` 0.75s ·
preroll/postroll/gap 200/300/50ms. Regra de mudança de config: precedência
CLI > env > `pipeline.toml` > default (skill `hardcoded-config-audit`).
