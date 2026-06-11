import unittest
from pathlib import Path


class ReviewWizardFrontendContractTests(unittest.TestCase):
    def test_app_js_initializes_audio_timeline_preview_sync(self):
        app_js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("initAudioTimelinePreview", app_js)
        self.assertIn("data-audio-timeline", app_js)
        self.assertIn("data-timeline-marker", app_js)
        self.assertIn("data-audio-playhead", app_js)
        self.assertIn("timeupdate", app_js)
        self.assertIn("data-audio-selection-readout", app_js)
        self.assertIn("preventDefault", app_js)
        self.assertIn("metaKey", app_js)
        self.assertIn("ctrlKey", app_js)
        self.assertIn("shiftKey", app_js)

    def test_observability_details_render_classifications_as_tags(self):
        app_js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("classificationDetailTags", app_js)
        self.assertIn("FRIENDLY_TAG_LABELS", app_js)
        self.assertIn("TAG_TITLES", app_js)
        self.assertIn("U-SUS", app_js)
        self.assertIn("W-MEL", app_js)
        self.assertIn("BV?", app_js)
        self.assertIn("Unwritten sustain", app_js)
        self.assertIn("Written melisma", app_js)
        self.assertIn("Backing vocal?", app_js)
        self.assertIn("formatTagLabel", app_js)
        self.assertIn("formatTagTitle", app_js)
        self.assertIn("renderDetailTag", app_js)
        self.assertIn('title="${escapeHtml(title)}"', app_js)
        self.assertIn("tail_classification", app_js)
        self.assertIn("line_classification", app_js)
        self.assertIn("diagnostic_tags", app_js)
        self.assertIn("review_flags", app_js)
        self.assertIn("${message ? escapeHtml(message) : details}", app_js)

    def test_review_wizard_css_extends_cockpit_visual_system(self):
        app_css = Path("static/app.css").read_text(encoding="utf-8")

        self.assertIn(".review-cockpit-shell", app_css)
        self.assertIn(".review-cockpit-sidebar", app_css)
        self.assertIn(".review-cockpit-command-strip", app_css)
        self.assertIn(".review-status-chips", app_css)
        self.assertIn(".review-cockpit-grid", app_css)
        self.assertIn(".review-cockpit-player", app_css)

    def test_review_wizard_css_covers_guided_ux_states(self):
        app_css = Path("static/app.css").read_text(encoding="utf-8")

        self.assertIn(".review-next-action", app_css)
        self.assertIn(".preview-approval-checklist", app_css)
        self.assertIn(".preview-media-placeholder", app_css)
        self.assertIn(".lyrics-review-guidance", app_css)
        self.assertIn(".quality-decision-note", app_css)
        self.assertIn(".review-risk-reason", app_css)


if __name__ == "__main__":
    unittest.main()
