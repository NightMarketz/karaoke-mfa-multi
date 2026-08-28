"""s07 tem de montar o canvas procedural quando ha backdrop.cmd."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.s07_output import (
    _build_backdrop_filter,
    _build_backdrop_source,
    _invalid_backdrop_cmd_reason,
    _invalid_backdrop_config_reason,
)


class BackdropSourceTests(unittest.TestCase):
    def test_source_is_a_gradients_with_fixed_colours(self):
        src = _build_backdrop_source("1920x1080", "30", 12.5,
                                     "0x0a0a18", "0x2a1060", "radial", 0.02)
        self.assertIn("gradients=", src)
        self.assertIn("s=1920x1080", src)
        self.assertIn("c0=0x0a0a18", src)
        self.assertIn("d=12.500", src)
        self.assertNotIn("color=c=black", src)


class BackdropFilterTests(unittest.TestCase):
    def test_no_cmd_file_yields_empty_filter(self):
        self.assertEqual("", _build_backdrop_filter(None))

    def test_cmd_file_yields_sendcmd_then_huesaturation(self):
        with TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "backdrop.cmd"
            cmd.write_text("0.000 huesaturation hue 0.0000;\n", encoding="utf-8")
            out = _build_backdrop_filter(cmd)
            self.assertTrue(out.startswith("sendcmd=f="), out)
            self.assertTrue(out.endswith(",huesaturation"), out)
            self.assertNotIn("\\\\", out, "caminho tem de usar barras normais")

    def test_windows_drive_colon_is_escaped(self):
        out = _build_backdrop_filter(Path("C:/jobs/x/backdrop.cmd"))
        self.assertIn("C\\:/jobs/x/backdrop.cmd", out)


class InvalidBackdropConfigReasonTests(unittest.TestCase):
    """Reproduz os 4 crashes de ffmpeg do finding 1 — cada um tem de virar
    fallback, nao abortar o render."""

    def test_valid_config_passes(self):
        self.assertIsNone(
            _invalid_backdrop_config_reason("radial", 0.02, "0x0a0a18", "0x2a1060")
        )

    def test_speed_above_one_is_rejected(self):
        # speed=5 -> "Error opening input files: Result too large"
        self.assertEqual(
            "invalid_speed",
            _invalid_backdrop_config_reason("radial", 5.0, "0x0a0a18", "0x2a1060"),
        )

    def test_zero_speed_is_rejected(self):
        self.assertEqual(
            "invalid_speed",
            _invalid_backdrop_config_reason("radial", 0.0, "0x0a0a18", "0x2a1060"),
        )

    def test_unknown_gradient_type_is_rejected(self):
        # type=bogus -> "Error opening input files: Invalid argument"
        self.assertEqual(
            "invalid_type",
            _invalid_backdrop_config_reason("bogus", 0.02, "0x0a0a18", "0x2a1060"),
        )

    def test_malformed_c0_is_rejected(self):
        # c0=nope -> "Error opening input files: Invalid argument"
        self.assertEqual(
            "invalid_c0",
            _invalid_backdrop_config_reason("radial", 0.02, "nope", "0x2a1060"),
        )

    def test_malformed_c1_is_rejected(self):
        self.assertEqual(
            "invalid_c1",
            _invalid_backdrop_config_reason("radial", 0.02, "0x0a0a18", "nope"),
        )

    def test_all_five_valid_gradient_types_pass(self):
        checked = 0
        for gtype in ("linear", "radial", "circular", "spiral", "square"):
            self.assertIsNone(
                _invalid_backdrop_config_reason(gtype, 0.02, "0x0a0a18", "0x2a1060"),
                gtype,
            )
            checked += 1
        self.assertEqual(5, checked, "denominador: 5 tipos validos")


class InvalidBackdropCmdReasonTests(unittest.TestCase):
    def test_valid_first_line_passes(self):
        with TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "backdrop.cmd"
            cmd.write_text("0.000 huesaturation hue -20.0000;\n", encoding="utf-8")
            self.assertIsNone(_invalid_backdrop_cmd_reason(cmd))

    def test_garbage_first_line_is_rejected(self):
        # "Error initializing filters" / "Error opening output files: Invalid argument"
        with TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "backdrop.cmd"
            cmd.write_text("garbage huesaturation hue 0.0000;\n", encoding="utf-8")
            self.assertEqual("invalid_cmd_format", _invalid_backdrop_cmd_reason(cmd))

    def test_blank_leading_lines_are_skipped(self):
        with TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "backdrop.cmd"
            cmd.write_text("\n\n0.000 huesaturation hue 0.0000;\n", encoding="utf-8")
            self.assertIsNone(_invalid_backdrop_cmd_reason(cmd))

    def test_only_blank_lines_is_empty(self):
        with TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "backdrop.cmd"
            cmd.write_text("\n\n", encoding="utf-8")
            self.assertEqual("empty", _invalid_backdrop_cmd_reason(cmd))
