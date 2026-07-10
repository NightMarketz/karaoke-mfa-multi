---
name: pap-ollama
description: Use when the user asks for local code generation via Ollama, token savings, or a Claude Code + Ollama loop ("gerar local", "economizar tokens", "rodar com Ollama"). Plan-Audit-Patch — the agent plans and audits, Ollama drafts locally, only a minimal verified patch is applied.
disable-model-invocation: true
---

# PAP-Ollama Workflow

Manual-only. Claude/Codex is the architect and auditor; Ollama is the local
executor. **Local model output is an untrusted draft** — never applied without audit.

## Core Rule
Nothing Ollama produces reaches the code until it is audited against the context
contract and reduced to the smallest verified patch.

## When to Use / When Not
- **Use when:** offloading bulk code generation to a local model to save tokens, on this repo's audio/alignment domain.
- **Do NOT use when:** a change is one line, security-sensitive, or needs judgment the local model can't verify — do it directly.

## SDD Contract (spec-first)
Before drafting, write the source of truth:
- **Context contract:** `.claude/tasks/context-contract.md` — the domain rules the draft must obey (audio processing, forced alignment, `min_dur` 50ms, `MIN_WORD_MS` 80ms, artifact contracts). See [../../../spec/PROJECT_CONSTITUTION.md](../../../spec/PROJECT_CONSTITUTION.md).
- **Must NOT change:** stage ids `s01–s08`, artifact names, the timing constants, the export gate.

## Required Workflow
1. **Domain context discovery** — write `.claude/tasks/context-contract.md`.
2. **Prompt** — write `.claude/tasks/current-prompt.md` for Ollama.
3. **Local execution** — run the draft:
   ```powershell
   .\.claude\skills\pap-ollama\scripts\run-ollama.ps1
   ```
4. **Audit & minimal patch** — review `.claude/tasks/current-output.md` against the context contract; apply only the smallest verified change.

## Common Mistakes
- Applying the draft wholesale instead of a minimal audited patch.
- Skipping the context contract (no spec = no gate).
- Letting the draft touch anything on the "must NOT change" list.

## Executable Verification
```bash
pytest tests
```
Pass criterion: suite green and no timing/artifact contract changed unless the
matching contract test was updated in the same commit.
