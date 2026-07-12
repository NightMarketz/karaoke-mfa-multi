# Uncommitted wip in tracked files

> tracked files (server.py, tests) carry large uncommitted WIP — stage hunks, not whole files

In the main checkout (`mvp-pipeline-runner` branch), many tracked files carry a
large body of **uncommitted working-tree changes** that are WIP for several
overlapping features. Notably `server.py` and `tests/test_server_contracts.py`:
as of 2026-07-10 the entire syllable-review backend (`/review/syllables/pending`,
`/audio/vocals/peaks`, POST `/review/syllables/boundary`, `_syllable_pending_queue`,
`_wav_window_peaks`) and pipeline-metrics helpers (`_compute_pipeline_metrics`)
lived only in the working tree, never committed — even though committed UI already
called them.

**Why:** `git add <wholefile>` on these sweeps ~hundreds of lines of unrelated WIP
into your commit. I hit this: a "Fase 4 onsets" commit accidentally bundled ~640
lines of pre-existing backend + metrics work.

**How to apply:** Before committing a change to a tracked file here, run
`git diff <file>` first. If it shows pre-existing unrelated changes, stage only
your hunks (`git add -p`) instead of the whole file — or confirm with the user
that bundling the WIP is intended. Self-contained new files (e.g.
`templates/syllable_editor.html`, `static/syllable_editor.js`) are safe to add
whole. Related: [karaoke-worktree-gitignored-source](karaoke-worktree-gitignored-source.md).
