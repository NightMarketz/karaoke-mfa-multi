# Highlight Velocity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first highlight-velocity layer so long sung syllables fill slowly across their real duration instead of filling quickly and freezing.

**Architecture:** Add a pure segmentation module that converts word timing into visual highlight fragments. Stage 06 consumes those fragments when building ASS karaoke tags, while the Review Wizard timeline receives a HIGHLIGHT lane so the user can inspect the visual timing separately from raw alignment.

**Tech Stack:** Python stdlib, unittest, Flask/Jinja templates, static CSS/JS already present in the project.

---

## File Structure

- Create `scripts/review_wizard/highlight_velocity.py`
  - Owns deterministic visual highlight segmentation.
  - Does not call audio models or mutate alignment.
- Modify `scripts/s06_generate_ass.py`
  - Uses highlight segments when present or derives them conservatively.
  - Keeps word spacing stable.
- Modify `scripts/review_wizard/audio_timeline.py`
  - Adds a HIGHLIGHT lane and accepts highlight markers.
- Modify `templates/review_wizard.html`
  - Renders the HIGHLIGHT lane through the existing lane loop.
- Modify `static/app.css`
  - Styles highlight markers distinctly.
- Add `tests/test_highlight_velocity.py`
- Modify `tests/test_ass_generation.py`
- Modify `tests/test_review_wizard_audio_timeline.py`

## Task 1: Highlight Segmentation Contract

- [ ] Write failing tests in `tests/test_highlight_velocity.py`.
- [ ] Verify RED with `python -m unittest tests.test_highlight_velocity`.
- [ ] Implement `scripts/review_wizard/highlight_velocity.py`.
- [ ] Verify GREEN with `python -m unittest tests.test_highlight_velocity`.

Required test behaviors:

```python
def test_short_word_remains_single_highlight_segment():
    segments = build_word_highlight_segments({"word": "to", "start": 10.0, "end": 10.18})
    assert [segment["text"] for segment in segments] == ["to"]
    assert segments[0]["start"] == 10.0
    assert segments[0]["end"] == 10.18

def test_long_word_slows_fill_on_vowel_nucleus():
    segments = build_word_highlight_segments({"word": "snap", "start": 275.42, "end": 282.02})
    assert [segment["text"] for segment in segments] == ["sn", "a", "p"]
    assert segments[0]["role"] == "consonant_attack"
    assert segments[1]["role"] == "sustained_vowel"
    assert segments[2]["role"] == "consonant_release"
    assert segments[0]["start"] == 275.42
    assert segments[-1]["end"] == 282.02
    assert segments[1]["end"] - segments[1]["start"] > 5.0
```

## Task 2: ASS Export Uses Highlight Segments

- [ ] Write failing tests in `tests/test_ass_generation.py`.
- [ ] Verify RED with `python -m unittest tests.test_ass_generation.AssGenerationTests.test_long_word_uses_slow_vowel_highlight_segments`.
- [ ] Modify `_build_karaoke_text`.
- [ ] Verify GREEN with the focused test.

Required behavior:

```python
def test_long_word_uses_slow_vowel_highlight_segments(self):
    text = _build_karaoke_text(
        [{"word": "snap", "start": 275.42, "end": 282.02}],
        line_start_ms=275420,
        effect="highlight",
    )
    self.assertIn("}sn{", text)
    self.assertIn("}a{", text)
    self.assertIn("}p", text)
    self.assertIn("\\kf", text)
    self.assertNotIn("sn a p", text)
```

## Task 3: Timeline HIGHLIGHT Lane

- [ ] Write failing tests in `tests/test_review_wizard_audio_timeline.py`.
- [ ] Verify RED with `python -m unittest tests.test_review_wizard_audio_timeline.AudioTimelineTests.test_build_audio_timeline_adds_highlight_lane`.
- [ ] Extend `build_audio_timeline` to accept highlight markers.
- [ ] Add CSS marker styling.
- [ ] Verify GREEN with the focused test.

Required behavior:

```python
def test_build_audio_timeline_adds_highlight_lane(self):
    points = []
    highlight_segments = [
        {"id": "line-1:word-1:hv-1", "text": "sn", "start_s": 1.0, "end_s": 1.1, "role": "consonant_attack"},
        {"id": "line-1:word-1:hv-2", "text": "a", "start_s": 1.1, "end_s": 3.8, "role": "sustained_vowel"},
    ]
    timeline = build_audio_timeline(points, duration_s=5.0, active_point_id=None, highlight_segments=highlight_segments)
    assert [lane["id"] for lane in timeline["lanes"]] == ["line", "word", "highlight", "issue"]
    assert timeline["lanes"][2]["markers"][1]["level"] == "highlight"
    assert timeline["lanes"][2]["markers"][1]["role"] == "sustained_vowel"
```

## Task 4: Verification And Agent Gates

- [ ] Run `python -m unittest tests.test_highlight_velocity tests.test_ass_generation tests.test_review_wizard_audio_timeline`.
- [ ] Run the wider Review Wizard and ASS suite.
- [ ] Run `python -m py_compile` on changed Python files.
- [ ] Run `node --check static\app.js`.
- [ ] Dispatch Review Agent for spec/code review.
- [ ] Fix important findings.
- [ ] Dispatch Approval Agent for final acceptance.
