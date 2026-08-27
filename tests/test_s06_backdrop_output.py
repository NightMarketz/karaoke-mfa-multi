"""s06 tem de emitir backdrop.cmd ao lado de output.ass."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("pysubs2")

from scripts.s06_generate_ass import _write_backdrop


class WriteBackdropTests(unittest.TestCase):
    def test_writes_file_without_bom(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            path = _write_backdrop(job, [{"color": "soft", "start": 0.0},
                                         {"color": "intense", "start": 4.0}])
            self.assertEqual(job / "backdrop.cmd", path)
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "sendcmd nao tolera BOM")
            self.assertEqual(6, len(raw.decode("utf-8").strip().splitlines()))

    def test_returns_none_and_writes_nothing_when_there_are_no_lines(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            self.assertIsNone(_write_backdrop(job, []))
            self.assertFalse((job / "backdrop.cmd").exists())

    def test_invalid_input_does_not_raise_out_of_the_stage(self):
        # Backdrop e' cosmetico: nunca derruba o s06.
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            bad = [{"color": "soft", "start": 0.0}, {"color": "warm", "start": -5.0}]
            self.assertIsNone(_write_backdrop(job, bad))
            self.assertFalse((job / "backdrop.cmd").exists())
