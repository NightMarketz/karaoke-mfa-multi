---
description: Workflow PAP local: Codex plans, Ollama drafts, Codex audits and applies a minimal patch.
disable-model-invocation: true
---

# PAP-Ollama Workflow

This is the canonical project-local PAP-Ollama skill for Codex.

## Stage 1 - Domain Context Discovery

Generate `.Codex/tasks/context-contract.md` with focus on audio processing,
forced alignment, minimum word duration, and karaoke timing constraints.

## Stage 2 - Prompt For Ollama

Generate `.Codex/tasks/current-prompt.md`.

## Stage 3 - Local Execution

Run:

```powershell
.\.Codex\skills\pap-ollama\scripts\run-ollama.ps1
```

## Stage 4 - Audit And Minimal Patch

Review `.Codex/tasks/current-output.md` against the context contract. Treat
local model output as an untrusted draft and apply only the smallest verified
patch.
