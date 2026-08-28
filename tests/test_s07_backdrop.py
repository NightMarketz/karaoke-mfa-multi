"""s07 tem de montar o canvas procedural quando ha backdrop.cmd."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.s07_output import _build_backdrop_filter, _build_backdrop_source


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
