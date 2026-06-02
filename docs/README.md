# Karaoke MFA Multi Documentation

This directory is the project knowledge base. Start here before changing
pipeline behavior.

## Primary Maps

- [Architecture](architecture/README.md) - runtime stages, data flow, and major
  code ownership boundaries.
- [Skills](skills/README.md) - local agent skills and PAP-Ollama workflow
  surfaces.
- [Skill Routing](skills/routing.md) - mandatory trigger map for deciding when
  project-local skills apply.
- [Skill Gap Analysis](skills/gap-analysis.md) - missing project skills and the
  evidence required before creating them.
- [Tasks](tasks/README.md) - task contracts and local execution artifacts.
- [Superpowers Specs](superpowers/specs/) - accepted design specs.
- [Superpowers Plans](superpowers/plans/) - implementation plans derived from
  specs.

## Current Rule

Pipeline refactors should start with an explicit context contract, evidence,
and tests. Local model output is always treated as an untrusted draft.
