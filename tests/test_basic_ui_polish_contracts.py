import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _css_block(css: str, selector: str) -> str:
    start = css.index(selector)
    open_brace = css.index("{", start)
    depth = 0
    for index in range(open_brace, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace + 1:index]
    raise AssertionError(f"CSS block not closed for {selector}")


class BasicUIPolishContracts(unittest.TestCase):
    def test_shared_templates_do_not_render_common_mojibake(self):
        for template in [
            ROOT / "templates" / "base.html",
            ROOT / "templates" / "new_job.html",
            ROOT / "templates" / "cockpit.html",
            ROOT / "templates" / "review_wizard.html",
            ROOT / "static" / "app.css",
        ]:
            with self.subTest(template=template.name):
                text = template.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"â[€œ€™¢”€\-]")
                self.assertNotIn("ðŸ", text)
                self.assertNotIn("🎤", text)

    def test_cockpit_navigation_uses_named_icon_classes_not_placeholder_glyphs(self):
        for template in [
            ROOT / "templates" / "cockpit.html",
            ROOT / "templates" / "review_wizard.html",
        ]:
            with self.subTest(template=template.name):
                text = template.read_text(encoding="utf-8")
                self.assertIn("cockpit-nav-icon icon-new", text)
                self.assertIn("cockpit-nav-icon icon-projects", text)
                self.assertIn("cockpit-nav-icon icon-review", text)
                self.assertNotIn('aria-hidden="true">[]</span>', text)
                self.assertNotIn('aria-hidden="true">*</span>', text)
                self.assertNotIn('aria-hidden="true">v</span>', text)
                self.assertNotIn('aria-hidden="true">o</span>', text)

    def test_mobile_cockpit_timeline_uses_viewport_width_not_fixed_canvas(self):
        css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
        mobile_block = re.search(
            r"@media \(max-width: 760px\) \{(?P<body>.*?)\n\}",
            css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(mobile_block)
        body = mobile_block.group("body")
        self.assertIn(".cockpit-wave-lanes", body)
        self.assertNotIn("min-width: 620px", body)
        self.assertIn("min-width: 0", body)
        self.assertIn("grid-template-columns: 4.25rem minmax(0, 1fr)", body)

    def test_review_timeline_bulk_markers_are_not_in_main_tab_order(self):
        template = (ROOT / "templates" / "review_wizard.html").read_text(encoding="utf-8")
        marker_start = template.index('class="audio-marker')
        marker_end = template.index("></a>", marker_start)
        marker_markup = template[marker_start:marker_end]
        self.assertIn('tabindex="{{ \'0\' if marker.is_active or loop.first else \'-1\' }}"', marker_markup)
        self.assertIn('aria-label="{{ marker.label }} {{ marker.display_title }}"', marker_markup)

    def test_review_alignment_dense_maps_have_visual_containment(self):
        css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
        map_block = _css_block(css, ".review-cockpit-grid .sync-map-track")
        queue_block = _css_block(css, ".review-cockpit-grid .review-point-window-list")

        self.assertIn("max-height:", map_block)
        self.assertIn("overflow: auto", map_block)
        self.assertIn("scrollbar-width: thin", map_block)
        self.assertIn("max-height:", queue_block)
        self.assertIn("overflow: auto", queue_block)
        self.assertIn("scrollbar-width: thin", queue_block)


if __name__ == "__main__":
    unittest.main()
