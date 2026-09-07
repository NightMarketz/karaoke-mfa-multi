# Phoneme word drift

> RESOLVED — s04 phoneme→word drift fixed via sequence (g2p-count) assignment + Icelandic lexicon; committed to mvp-pipeline-runner

**RESOLVED 2026-07-11** (commits `74e5a487` + `2aef35f6` on branch `mvp-pipeline-runner`, pushed).

FIX SHIPPED in `scripts/s04_align.py`:
- `--phone-assign sequence` (default): assign the ordered HubertFA phone stream to words by the REAL per-word g2p phone count (`_phonemise_text` now runs per-word, storing `_ph_counts`), instead of time-bucketing into unreliable CTC word spans. Same lexicon-count grouping MFA/SOFA use. Per-segment fallback to the old `timebucket` if the count invariant breaks (never fired on real data). Whisper mode (`_map_phonemes_to_words`) got the same real-count split.
- Optional Icelandic lexicon `models/hubertfa/is_pron_dict.txt` (176 words; word→nearest en/ ARPAbet). Listed words bypass g2p_en (which mangles Icelandic spelling); unlisted Icelandic-spelled words fall back to g2p_en and are logged. The model has no native Icelandic phones (vocab is en/ja/zh only), so labels are ARPAbet approximations — good for vowel/syllable count, not exact phonetics.

VALIDATED (InnerBeast 354w + Struggle 260w, real HubertFA runs, 4 independent methods):
- Starved words (0 phonemes): 44/5 → 0. Group inversions: 0. Guard fallbacks: 0 across 138 segments.
- Render (ASS \k onsets): sequence highlights each word ~0.13s from the sung moment vs ~0.39s for timebucket (~3× closer).
- HubertFA native word-tier oracle (DictionaryG2P): endorses the count grouping 100%; its acoustic word boundaries track the phoneme times (0.16s), NOT the CTC spans (0.52s) → confirms CTC word timing is drifted ~0.5s, but render uses phoneme times (`s05_analyze.py` `vowel_start`) so it's robust.
- Icelandic syllable-count correctness 81% → 100%.
- `demo()` self-check + 77 s04/align tests pass.

KNOWN RESIDUAL (not blocking): CTC word SPANS drift ~0.5s on sustained vocals (upstream of s04, both modes inherit them); render is phoneme-time-driven so unaffected. Icelandic phone LABELS remain ARPAbet approximations (no native is/ phone set in the model). Only 2 distinct songs exist in the repo, so corpus breadth is limited.

--- ORIGINAL DIAGNOSIS (kept for context) ---
Root cause was `_ctc_forced_with_phonemes`: it assigned each HubertFA phoneme to a word by time-bucketing into the CTC word span containing the phone midpoint. CTC word spans are unreliable on sung/sustained vocals, so phones landed in the neighbouring word's bucket. DECISIVE PROOF (English, no special aligner): line "The beast beneath my skin" — HubertFA phone stream `DH AH | B IY S T | B IH N IY TH | M AY | S K IH N` is an exact 17-phone match to the per-word g2p concat, so phone alignment (times+order) was CORRECT; only the word bucketing failed (`The` grabbed The+beast, `beast` grabbed beneath, `my` starved). NOT a language/g2p problem — English broke equally, which overturned the earlier "activate native Icelandic aligner (SOFA/ROSVOT)" plan.

Also kept: `scripts/review_wizard/highlight_velocity.py` `build_word_highlight_segments` guard (sustain-split only when `_vowel_run_count(text)==1`). Related: [karaoke-syllable-render-state](karaoke-syllable-render-state.md), [karaoke-pending-queue-driver](karaoke-pending-queue-driver.md), [karaoke-uncommitted-wip-in-tracked-files](karaoke-uncommitted-wip-in-tracked-files.md).
