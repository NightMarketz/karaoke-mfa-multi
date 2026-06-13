# Basic UI Audit Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the basic UI issues found during the rendered screen sweep.

**Architecture:** Preserve the existing Flask/Jinja/static CSS architecture. Use contract tests to lock in mobile cockpit behavior, clean shared template text, and review-wizard navigation density.

**Tech Stack:** Python unittest, Flask/Jinja templates, static CSS/JS, Browser/IAB QA.

---

### Task 1: UI Contract Tests

**Files:**
- Create: `tests/test_basic_ui_polish_contracts.py`

- [ ] Add tests that assert shared templates do not contain common mojibake sequences.
- [ ] Add tests that assert mobile cockpit CSS removes the fixed 620px timeline width.
- [ ] Add tests that assert review timeline markers are removed from the main tab order.
- [ ] Run `python -m unittest tests.test_basic_ui_polish_contracts` and confirm the new tests fail before implementation.

### Task 2: Template Cleanup

**Files:**
- Modify: `templates/base.html`
- Modify: `templates/new_job.html`
- Modify: `templates/review_wizard.html`

- [ ] Replace corrupted visible separators with HTML entities or ASCII text.
- [ ] Replace the favicon corrupted microphone text with a simple generated `K` mark.
- [ ] Add `tabindex="-1"` to dense audio timeline marker links while leaving the queue links keyboard reachable.
- [ ] Run the focused UI contract tests.

### Task 3: Mobile Cockpit CSS

**Files:**
- Modify: `static/app.css`

- [ ] Change mobile cockpit timeline lanes to fit the viewport instead of forcing `min-width: 620px`.
- [ ] Compact lane label columns and waveform/marker rows for small screens.
- [ ] Keep desktop cockpit and review wizard layouts unchanged.
- [ ] Run the focused UI contract tests.

### Task 4: Verification

**Files:**
- No production edits expected.

- [ ] Run `python -m unittest tests.test_basic_ui_polish_contracts tests.test_review_wizard_frontend_contracts`.
- [ ] Start the Flask app and run Browser/IAB QA for `/`, `/?job=abc123def456`, `/job/new`, `/job/abc123def456`, and `/job/abc123def456/review?stage=alignment`.
- [ ] Check desktop plus mobile `390x844` for console errors and horizontal layout regressions.
