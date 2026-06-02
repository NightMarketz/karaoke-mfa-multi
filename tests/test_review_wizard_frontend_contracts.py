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


if __name__ == "__main__":
    unittest.main()
