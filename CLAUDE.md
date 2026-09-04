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

## Tronco e colheita

- **Tronco:** `mvp-pipeline-runner`. Todo trabalho volta para cá. Refs protegidas,
  nunca arquivadas: `mvp-pipeline-runner`, `master`, `main`.
- **Comando de teste:** `pytest tests` — com o argumento. `pytest` na raiz mede
  outra população: transforma `pytest.importorskip` em erro de coleta.
- **Portão de merge:** `pytest tests` verde **no resultado do merge**, não na branch
  isolada. Vermelho desfaz o merge.
- **Colheita:** antes de despachar uma frente nova, rode
  `python scripts/branch_harvest.py --reap` e resolva o destino das branches
  existentes. Branch sem ancestral comum com o tronco não é mergeável — arquivar ou
  portar à mão, nunca `git merge`.
- Desenho e medição que originaram isto:
  `docs/superpowers/specs/2026-09-04-colheita-de-branches-design.md`.
