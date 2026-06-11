# Skills Inventory

This page lists the current project-local skills. Use
[Skill Routing](routing.md) to decide when a skill applies, and use
[Skill Gap Analysis](gap-analysis.md) before creating new skills.

## Active Project Skills

- `.Codex/skills/pap-ollama/SKILL.md` - canonical PAP-Ollama workflow.
- `.Codex/skills/hardcoded-config-audit/SKILL.md` - evidence-first audit for
  hardcoded paths, models, thresholds, defaults, and configuration refactors.

## Canonical Codex Skill

- `.Codex/skills/pap-ollama/SKILL.md`

This is the project-local Codex PAP-Ollama workflow referenced by `AGENTS.md`.
It writes prompts and outputs under `.Codex/tasks`.

## Compatibility Skills

- `.claude/skills/pap-ollama/SKILL.md`
- `.agents/skills/pap-ollama/SKILL.md`

The `.claude` skill is referenced by `CLAUDE.md`. The `.agents` folder exists
locally for Antigravity-style agent workflows and is ignored by git, so it
should not be treated as the repository source of truth.

## PAP-Ollama Rule

Codex plans and audits. Ollama drafts locally. Any output from Ollama must be
checked against the context contract before code is changed.

## Creation Rule

Do not create a new skill just because a workflow is repeated once. Create a
skill only when the gap analysis identifies repeated work, clear project rules,
and testable verification criteria.
