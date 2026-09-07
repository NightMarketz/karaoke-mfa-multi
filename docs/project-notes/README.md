# Project notes

_Mirrored from Claude Code project memory. Source of truth is the assistant's memory store; this copy is versioned for team visibility._

- [Worktree gitignored source](karaoke-worktree-gitignored-source.md) — real pipeline code is gitignored; worktrees are empty, work in main checkout
- [Syllable render state](karaoke-syllable-render-state.md) — how syllabic highlight reaches the video (syllables field, render precedence, source-aware confidence)
- [Pending queue driver](karaoke-pending-queue-driver.md) — review queue is phone-driven; fixed by trusting HubertFA-measured timing in syllables.py confidence (not the word-duration floor)
- [Uncommitted WIP in tracked files](karaoke-uncommitted-wip-in-tracked-files.md) — server.py/tests carry big uncommitted WIP; stage hunks not whole files
- [Phoneme→word drift](karaoke-phoneme-word-drift.md) — RESOLVED 2026-07-11: fixed via `--phone-assign sequence` (g2p-count) + 176-word Icelandic lexicon; commits 74e5a487+2aef35f6 on mvp-pipeline-runner
