# Context Contract: Project Knowledge Base

## Objective

Organize the project knowledge surface before structural pipeline refactors.
The repository must make skills, task contracts, specs, plans, and architecture
entry points easy to find and mechanically checkable.

## Scope

- Add navigation documentation for project knowledge and agent workflows.
- Add a canonical Codex PAP-Ollama skill under `.Codex/skills`.
- Preserve existing `.claude` and `.agents` skill copies for compatibility.
- Add tests that validate documented workflow paths and primary markdown links.

## Non-Goals

- Do not refactor pipeline runtime code in this task.
- Do not move or delete existing `.claude` or `.agents` content.
- Do not change audio alignment thresholds or rendering behavior.

## Required Behavior

- `AGENTS.md` workflow paths resolve on disk.
- `CLAUDE.md` workflow paths continue to resolve on disk.
- The project has a docs landing page that points to specs, plans, tasks,
  architecture notes, and skill inventory.
- The documentation index has no broken local markdown links.

## Verification

- Run `python -m unittest tests.test_project_knowledge_base`.
- Confirm no existing pipeline files are modified by this organization task.
