# Context Contract: Highlight Velocity

## Objective

Implement the first local karaoke highlight-velocity layer. Long sung syllables must not use a fast fill followed by a static hold. The visible fill should span the sung duration by splitting the displayed text into timed visual fragments, so sustained vowels move more slowly and finish with the vocal timing.

## Scope

- No Suno API usage.
- Do not change raw alignment timestamps.
- Add a deterministic highlight segmentation layer used by ASS generation and Review Wizard timeline display.
- Keep implementation incremental and isolated.
- All tests must run with explicit timeouts.

## Required Behavior

- A normal short word keeps one visual highlight segment.
- A long sung word with consonant attack, vowel sustain, and consonant release is split into contiguous visual fragments.
- Segment durations must preserve the original word start/end.
- The sustained vowel segment receives the long duration, producing slower fill speed.
- ASS export must render contiguous fragments without spaces inside a word.
- Review Wizard timeline must expose a HIGHLIGHT lane for segment review.

## Non-Goals

- No new forced-alignment model.
- No full phoneme recognizer in this slice.
- No destructive rewrite of lyrics.
- No duplicate melisma text unless lyrics explicitly repeat it.

## Verification

- Unit tests for highlight segmentation.
- ASS generation tests for long words and explicit highlight segments.
- Review Wizard timeline tests for highlight lane markers.
- Existing review wizard and ASS tests must still pass.
