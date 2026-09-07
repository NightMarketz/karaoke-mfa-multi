# Worktree gitignored source

> karaoke-mfa-multi's real pipeline source is gitignored; git worktrees are empty of it, work in the main checkout

In `karaoke-mfa-multi`, the actual working pipeline is **untracked/gitignored** and lives only in the main checkout `C:\Users\Katz\OneDrive\Desktop\Meus projetos\karaoke-mfa-multi\`: `scripts/s01..s08_*.py`, `scripts/review_wizard/*.py`, `scripts/common/*.py`, `scripts/karaoke_styles/*.py`, `pipeline.toml`, and most `tests/test_*.py` (the `.gitignore` has broad rules like `test_*`, `*.txt`, and the source tree was never committed).

Git only tracks a smaller, different subset: numbered `scripts/01_..13_*.py` and the `karaoke/` package.

**Consequence:** a fresh `git worktree` checks out only tracked files, so the real code is MISSING there (only stale `.pyc` in `__pycache__` remain). Do pipeline work directly in the main checkout — a worktree gives no isolation benefit here since the target files aren't version-controlled anyway.

**Why:** confirmed 2026-07-10 while implementing syllable-render work; the spec targeted files that didn't exist in the worktree.
**How to apply:** for any task touching s0x/review_wizard/common/tests in this repo, read/edit via absolute paths under the main checkout, and run `python -m pytest` there (flask/numpy/pysubs2 are installed). See [karaoke-syllable-render-state](karaoke-syllable-render-state.md).
