# Timing Classification Report

## Scope

Stage 06 keeps two timing layers:

- `timing_layers`: structural timing inferred from `analysis.json`.
- `timing_audio_layers`: audio-backed timing inferred from `vocals.wav` when available.

Local audio evidence may extend or trim final-word timing only for explicitly safe classes.
Everything else is review-only.

## Evidence Table

| ID | File | Value | Classification | Risk | Decision | Test |
| --- | --- | --- | --- | --- | --- | --- |
| H001 | `scripts/review_wizard/timing_layers.py` | textual melisma attached-region window `0.75s` | domain constant | Too wide could attach unrelated interline vocals. | Apply only when final word is a written textual melisma and the attached region is active. Non-melisma tails keep the tighter `0.35s` window. | `test_audio_backed_timing_extends_written_melisma_with_late_attached_region` |
| H002 | `scripts/review_wizard/vocal_activity.py` | noise threshold capped at `strong * 0.50` | domain constant | Too low could mark steady noise as vocal; too high misses continuous synthetic/controlled vocals. | Preserve noise-floor gating but cap it so continuous voiced fixtures do not classify all frames inactive. | `test_detects_continuous_synthetic_vocal_without_silent_noise_floor` |
| H003 | `scripts/review_wizard/timing_layers.py` | written melisma attached-tail minimum `0.20s` | domain constant | Too low could extend tiny consonant bleed or breath into text. | Apply only to written textual melismas with active tail evidence; this captures short but continuous cases such as `Oooo wooow`. | `test_audio_backed_timing_extends_short_attached_written_melisma_tail` |
| H004 | `scripts/review_wizard/timing_layers.py` | audio-extension final-word maximum `0.60s` | domain constant | Too wide could turn normal short words before instrumental pauses into rendered sustains. | Require strong tail evidence for automatic extension; moderate evidence remains review-only. | `test_audio_backed_timing_promotes_strong_tail_after_fear` |

## Audio-Backed Classes

| Class | Meaning | Render behavior | Review guidance |
| --- | --- | --- | --- |
| `written_melisma_extension` | A written melisma such as `Hmmmmm`, `oooohh`, or `Oooo wooow` has attached vocal activity after the aligned word end. | Extend the final written word to the detected vocal-region end. | Verify the extension follows lead vocal, especially when the detected region starts late in the interline gap. |
| `probable_unwritten_vowel_extension` | A short final word is followed by strong continuous vocal evidence before the next line. | Extend the final word when evidence is strong. | Confirm the singer is sustaining the written final vowel. |
| `possible_lost_tail` | A short final word has moderate vocal-tail evidence, but not enough confidence for automatic rendering. | Review-only; no automatic extension. | Review local alignment around the word and decide whether to extend the final vowel. |
| `unwritten_interline_melisma` | A long aligned final word is followed by additional vocal material between lyric lines. | Review-only for now. | Keep as diagnostic unless product explicitly adds visual extension bars or attaches safe interline tails. |
| `false_long_tail` | A long final-word timestamp has weak or inactive vocal evidence. | Trim final word to a conservative minimum. | Confirm the trim does not remove intentional breathy or quiet lead vocal. |
| `review_only_backing_or_drift` | A line has suspicious internal gaps with audio-supported words, often backing vocal, drift, or local realignment failure. | No automatic correction. | Inspect whether backing vocals are not in lyrics, or realign the local phrase. |

## Diagnostics

| Diagnostic | Meaning | Recommended fallback |
| --- | --- | --- |
| `possible_backing_vocal_not_in_lyrics` | Audio supports words around a suspicious internal gap, but the line is unsafe to auto-fix. | `manual_review_or_local_realign` |
| `final_word_after_alignment_hole` | A very short final word appears after a large internal alignment hole, as in `sealed in the tomb`. | `review_local_realignment` |
| `previous_tail_likely_stolen_by_next_line` | The next lyric line starts before the previous line has ended, suggesting phrase-boundary drift. | `extend_previous_tail_or_move_next_line_start_later` |
| `early_next_line_entry_drift` | The first word of the next line enters during the previous line tail, such as early `I'm`. | `move_line_start_later_or_review_previous_tail` |

## Manifest Fields

`output.ass.manifest.json` records:

- `timing_audio_layers.summary`: counts by gap, vocal period, and tail class.
- `timing_audio_layers.applied_tail_extensions`: count of safe rendered extensions.
- `timing_audio_layers.applied_tail_trims`: count of rendered false-tail trims.
- `timing_audio_layers.diagnostics`: compact review-only evidence for backing vocal or drift classes.

## Product Decision

`unwritten_interline_melisma` remains diagnostic/review-only. Stage 06 does not render silent extension bars or attach unwritten interline vocals until there is a separate product decision and visual QA coverage.
