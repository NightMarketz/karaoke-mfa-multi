"""s06 tem de emitir backdrop.cmd ao lado de output.ass."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

pytest.importorskip("pysubs2")

from scripts.s06_generate_ass import _write_backdrop


class WriteBackdropTests(unittest.TestCase):
    def test_writes_file_without_bom(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            path, count = _write_backdrop(job, [{"color": "soft", "start": 0.0},
                                                 {"color": "intense", "start": 4.0}])
            self.assertEqual(job / "backdrop.cmd", path)
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "sendcmd nao tolera BOM")
            lines = raw.decode("utf-8").strip().splitlines()
            self.assertEqual(6, len(lines))
            self.assertEqual(len(lines), count, "contagem devolvida tem de bater com o arquivo")

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

    def test_empty_content_removes_a_stale_backdrop_cmd(self):
        # Re-run sem linhas coloridas: o fundo da corrida anterior nao
        # corresponde mais a analise atual — o s07 nao pode encontrar um
        # backdrop.cmd velho e renderizar com timings obsoletos.
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "backdrop.cmd").write_text("OLD", encoding="utf-8")
            self.assertIsNone(_write_backdrop(job, []))
            self.assertFalse((job / "backdrop.cmd").exists())

    def test_invalid_content_removes_a_stale_backdrop_cmd(self):
        # Mesmo caso, mas a falha e' de geracao (timestamp invalido), nao
        # de ausencia de linhas.
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "backdrop.cmd").write_text("OLD", encoding="utf-8")
            bad = [{"color": "soft", "start": 0.0}, {"color": "warm", "start": -5.0}]
            self.assertIsNone(_write_backdrop(job, bad))
            self.assertFalse((job / "backdrop.cmd").exists())

    def test_write_is_atomic_no_tmp_file_left_behind(self):
        # Escrita normal (sem falha): nenhum .tmp sobra no diretorio.
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            _write_backdrop(job, [{"color": "soft", "start": 0.0},
                                   {"color": "intense", "start": 4.0}])
            self.assertEqual(["backdrop.cmd"], sorted(p.name for p in job.iterdir()))

    def test_failed_write_does_not_clobber_existing_backdrop_cmd(self):
        # Discriminador: um write direto (nao-atomico) ja teria truncado/
        # sobrescrito o backdrop.cmd anterior antes de falhar. A versao
        # atomica escreve no .tmp primeiro — se isso falha, o arquivo
        # existente nunca e' tocado, e nenhum .tmp sobra.
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            existing = job / "backdrop.cmd"
            existing.write_text("OLD", encoding="utf-8")

            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                result = _write_backdrop(job, [{"color": "soft", "start": 0.0},
                                                {"color": "intense", "start": 4.0}])

            self.assertIsNone(result)
            self.assertEqual("OLD", existing.read_text(encoding="utf-8"))
            self.assertEqual(["backdrop.cmd"], sorted(p.name for p in job.iterdir()))
