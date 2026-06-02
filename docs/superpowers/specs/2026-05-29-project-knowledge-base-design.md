# Project Knowledge Base Design

## Goal

Make project knowledge discoverable before changing structural pipeline
configuration. The immediate problem is not only hardcoded values; it is that
skills, task contracts, specs, and plans are spread across several agent
surfaces with no canonical map.

## Current Evidence

- `AGENTS.md` declares `.Codex/tasks/context-contract.md` and
  `.\.Codex\skills\pap-ollama\scripts\run-ollama.ps1`.
- `.Codex/tasks` exists, but `.Codex/skills` was missing.
- `.agents/skills/pap-ollama` exists locally, but `.agents/` is ignored by git.
- `.claude/skills/pap-ollama` exists and is referenced by `CLAUDE.md`.
- Specs and plans exist under `docs/superpowers`, but there was no root docs
  landing page.

## Architecture

Use `.Codex` as the Codex workflow surface because `AGENTS.md` already names it.
Keep `.claude` and `.agents` as compatibility surfaces. Documentation should
describe all three instead of hiding the mismatch.

The first implementation slice adds navigation and tests only. Later refactors
can use these indexes and checks before moving files or centralizing pipeline
configuration.

## Components

- `.Codex/skills/pap-ollama`: canonical Codex PAP-Ollama skill.
- `.Codex/tasks/project-knowledge-base-contract.md`: task contract for this
  organization slice.
- `docs/README.md`: top-level documentation map.
- `docs/skills/README.md`: skill inventory and ownership.
- `docs/tasks/README.md`: task contract inventory.
- `docs/architecture/README.md`: current architecture map.
- `tests/test_project_knowledge_base.py`: inventory and link validation.

## Testing

The tests intentionally check project structure rather than implementation
details. They verify that the paths advertised to agents exist, every canonical
skill has required files, and the documentation landing pages do not contain
broken local markdown links.

## Follow-Up

After this slice passes, the hardcoded-configuration SDD task can reference the
knowledge base and add evidence for each structural refactor.
