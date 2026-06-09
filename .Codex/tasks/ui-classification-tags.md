# Task: UI Classification Tags

## Objective

Transform timing and audio diagnostic classifications into visible UI tags in the Review Wizard, so reviewers can scan cases such as `written_melisma_extension` without reading long diagnostic text.

## Context

Stage 06 already records audio-backed timing decisions in `output.ass.manifest.json` under `timing_audio_layers`. Review Wizard currently converts these diagnostics into quality review points, but the important classifications are mostly embedded in plain text.

Relevant existing classes and labels include:

- `written_melisma_extension`
- `probable_unwritten_vowel_extension`
- `possible_lost_tail`
- `unwritten_interline_melisma`
- `false_long_tail`
- `review_only_backing_or_drift`
- `review_only_low_vocal_evidence`
- `possible_backing_vocal_not_in_lyrics`
- `final_word_after_alignment_hole`
- `early_next_line_entry_drift`
- `line_low_vocal_evidence`
- `structural_pause_overridden_by_audio_tail`
- `long_structural_pause_audio_extension`

## Scope

- Add structured tags/chips to Review Wizard review points derived from timing-audio diagnostics.
- Preserve the existing point text, suggested action, evidence summary, and status behavior.
- Surface tags in the active review point header and in the review queue item.
- Use current CSS tag/chip conventions where possible.
- Keep tags data-driven from manifest diagnostics instead of hardcoding a single display string in the template.

## Required Behavior

- A timing-audio review point for `written_melisma_extension` shows a visible tag such as `WRITTEN MELISMA EXTENSION`.
- Review-only classes show tags that make the review-only nature clear, for example `REVIEW ONLY` plus the specific class.
- `diagnostic_tags` from line-level diagnostics are shown as separate tags.
- `review_flags` are shown as separate lower-emphasis warning tags.
- `sound_suggestion.sound_type` may be shown as a tag only when it adds information not already represented by the main class or diagnostic tags.
- Tag labels replace underscores with spaces and use uppercase display text.
- Empty or duplicate tags are removed before rendering.

## Non-Goals

- Do not change raw alignment timestamps.
- Do not change Stage 06 classification logic.
- Do not auto-render suggested captions such as `[vocalizacao]` or `[vocal de apoio]`.
- Do not make `unwritten_interline_melisma` an automatic ASS render behavior.
- Do not rewrite the Review Wizard workflow or export gate behavior.

## Suggested Implementation

1. Extend `scripts/review_wizard/review_points.py` so `ReviewPoint` can carry a list of structured tags.
2. Build those tags in `_audio_timing_points()` from:
   - `tail_classification`
   - `line_classification`
   - `diagnostic_tags`
   - `review_flags`
   - useful `sound_suggestion.sound_type`
3. Update `ReviewPoint.to_dict()` if serialized point data needs to expose the tags.
4. Update `templates/review_wizard.html` to render tags for:
   - `active_point`
   - queue items in `review_point_window`
5. Add focused CSS classes in `static/app.css` only if existing `.tag` styles are not enough.

## Verification

- Add or update unit tests for `scripts/review_wizard/review_points.py` proving `written_melisma_extension` becomes a visible tag.
- Test deduplication when the same classification appears in multiple diagnostic fields.
- Test review-only diagnostics expose a `REVIEW ONLY` tag.
- Add or update a server/template contract test proving rendered Review Wizard HTML contains the classification tag text.
- Run relevant tests with explicit commands, for example:
  - `python -m unittest tests.test_timing_layers`
  - `python -m unittest tests.test_server_contracts`

## Audit Notes

- Treat model or manifest classifications as diagnostic evidence, not truth.
- The UI should help the reviewer inspect timing decisions; it must not imply that review-only suggestions were applied.
- `written_melisma_extension` is the example priority because it is a safe rendered extension class, but the implementation should support the full diagnostic set above.
