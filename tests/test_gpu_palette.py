"""The GPU renderer's palette must come from the chosen preset and keep the
sung half the brighter one, because that renderer's bloom keys off luminance.
"""
import unittest

from tests._optional_imports import import_or_skip

import_or_skip("numpy")
import_or_skip("soundfile")

from scripts.karaoke_styles.library import get_preset, list_preset_ids
from scripts.s06b_render_gpu import _hex, _luma, _palette


class GpuPaletteTests(unittest.TestCase):
    def test_hex_conversion_reads_ass_bgr(self):
        # ASS stores &HAABBGGRR — blue and red are swapped relative to hex.
        self.assertEqual("#FF0000", _hex("&H000000FF"))
        self.assertEqual("#0000FF", _hex("&H00FF0000"))
        self.assertEqual("#FFFFFF", _hex("&H00FFFFFF"))

    def test_palette_covers_every_style_of_every_preset(self):
        checked = 0
        for preset_id in list_preset_ids():
            styles = get_preset(preset_id).styles
            palette = _palette(preset_id)
            self.assertEqual(set(styles), set(palette), preset_id)
            checked += len(palette)
        self.assertGreaterEqual(checked, 135, "preset library shrank - fence no longer covers it")

    def test_sung_is_never_dimmer_than_waiting(self):
        # Most presets are brighter on the waiting side; that reads fine through
        # libass but would make the GPU bloom light the not-yet-sung text.
        checked = 0
        offenders = []
        for preset_id in list_preset_ids():
            for key, colors in _palette(preset_id).items():
                checked += 1
                if _luma(colors["sung"]) < _luma(colors["wait"]):
                    offenders.append(f"{preset_id}/{key}: {colors}")
        self.assertGreaterEqual(checked, 135)
        self.assertEqual([], offenders, f"{len(offenders)} of {checked} would bloom the wrong half")

    def test_waiting_stays_legible_on_the_black_canvas(self):
        # Dimming must not push the waiting text into the background.
        for preset_id in list_preset_ids():
            for key, colors in _palette(preset_id).items():
                source = get_preset(preset_id).styles[key].primary_color
                self.assertLessEqual(
                    _luma(colors["wait"]), _luma(_hex(source)) + 0.01,
                    f"{preset_id}/{key} got brighter, not dimmer",
                )

    def test_preset_hues_survive_the_dimming(self):
        # The waiting colour is scaled, never replaced, so its hue ratio holds.
        colors = _palette("aegisub-impact-red")["verse"]
        r, g, b = (int(colors["wait"][i:i + 2], 16) for i in (1, 3, 5))
        self.assertEqual(r, g)
        self.assertEqual(g, b)
        self.assertEqual("#EB4E34", colors["sung"])


if __name__ == "__main__":
    unittest.main()
