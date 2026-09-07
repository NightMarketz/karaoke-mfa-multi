# Pending queue driver

> Syllable review queue is phone-driven, not word-duration-driven; a word-duration floor barely moves it

Measured (2026-07-10) on jobs/beef12345678 (the "dýrið"/"Ice"/"dress" job) and jobs/9d447da775e0:
the syllable review queue (`server._syllable_pending_queue`) is NOT meaningfully reduced by a word-duration
floor. Pending went 30→29 (9d447da) and 20→20 (beef) with a 120ms floor in s04.

**Why:** syllable confidence in [karaoke-syllable-render-state](karaoke-syllable-render-state.md) (`scripts/syllables.py::syllable_confidence`)
is computed from the **phone-group span**, not the word span. The dominant low-confidence drivers are:
(1) `duration_plausibility` penalizing short phone spans of genuinely-fast function words, (2) the CTC
`probability` ×0.5 downgrade, (3) over-long held-note syllables (>1.2s), (4) `word_boundary_fit`. None are
fixable by word-level timing — extending a word span to cover its phones left pending unchanged (65→65),
because the phone-group span (hence duration_plausibility) is untouched.

Many "degenerate ~60ms" words on beef are **wedged** (abut neighbors, gap=0) and their HubertFA phonemes
confirm ~60ms — genuinely fast singing, NOT CTC compression. Flooring them would over-extend past the real
sung duration. The word-duration floor only safely helps **island** words (silence on both sides, phones in
the gap) — a rendering-quality win (no ~50ms flashing highlights), not a queue-size win.

**Resolution (2026-07-10):** fixed in `scripts/syllables.py::syllable_confidence` — split into two branches.
When phone timing is HubertFA-measured (`_has_measured_phone_timing`: source contains "hubertfa", or empty
with phones), the source base dominates and duration/boundary give at most a ~15% haircut (never forces
review), and stale CTC probability is ignored — fast function words and held notes clear the queue. Guessed
timing (phone-less fallback, `ctc_forced`, interpolated) keeps the strict blend + probability downgrade.
`low_confidence` still forces review in both branches. Result: beef & 9d447da review queues 20/30 → 0
(fully-HubertFA jobs have nothing boundary-editable); the queue still surfaces guessed-timing and
low_confidence words. The word-duration floor in s04 (`align.min_word_ms`, default 120) is a separate,
kept rendering-quality fix (no ~50ms island highlights); it is NOT the queue lever.
