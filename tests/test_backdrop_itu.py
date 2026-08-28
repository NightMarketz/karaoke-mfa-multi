"""Cerca de fotossensibilidade (ITU-R BT.1702-3) sobre o video renderizado.

Mede luminancia por frame na faixa da letra e exige variacao < 20 cd/m2.
Traz o proprio controle negativo: um estrobo deliberado tem de ficar vermelho,
senao a cerca nao discrimina e o verde nao vale nada.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts.karaoke_styles.backdrop import emit_backdrop_commands
from scripts.s07_output import _ffmpeg_path

if shutil.which("ffmpeg") is None:
    pytest.skip("ffmpeg nao encontrado no PATH", allow_module_level=True)

THRESHOLD_CDM2 = 20.0


def _luma_series(src: Path, crop: str | None = None) -> list[float]:
    vf = (f"{crop}," if crop else "") + "signalstats,metadata=print:key=lavfi.signalstats.YAVG"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-vf", vf, "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    return [float(m) for m in re.findall(r"YAVG=([0-9.]+)", proc.stderr)]


def _cdm2(code8: float) -> float:
    """8-bit YAVG -> cd/m2. BT.1702-3 Annex 2 + EOTF BT.1886, peak white 200."""
    v = (code8 * 4 - 64) / 876.0
    return 200.0 * max(v, 0.0) ** 2.4


def _delta(series: list[float]) -> float:
    lums = [_cdm2(x) for x in series]
    return max(lums) - min(lums)


def _render(dst: Path, vsrc: str, duration: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", vsrc,
         "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", str(dst)],
        check=True, capture_output=True, timeout=120,
    )
    return dst


class PhotosensitivityFenceTests(unittest.TestCase):
    def test_procedural_backdrop_stays_under_the_flash_threshold(self):
        # Cerca contra a cadeia REAL que o s07 monta: gradients -> sendcmd(f=
        # backdrop.cmd) -> huesaturation. Um teste que so' renderiza
        # `gradients` sozinho (sem sendcmd/huesaturation/ass) nao mede o
        # risco de flash — ele vive inteiro nas trocas de secao do sendcmd.
        with TemporaryDirectory() as tmp:
            lines = [
                {"color": "soft", "start": 0.0},
                {"color": "warm", "start": 0.5},
                {"color": "intense", "start": 1.0},
                {"color": "cool", "start": 1.5},
            ]
            distinct_colours = {line["color"] for line in lines}
            self.assertGreaterEqual(
                len(distinct_colours), 3,
                "fixture tem de ter >=3 trocas de cor para exercitar o risco real",
            )
            cmd_path = Path(tmp) / "backdrop.cmd"
            cmd_path.write_text(emit_backdrop_commands(lines) + "\n", encoding="utf-8")

            vsrc = (
                "gradients=s=320x180:r=30:c0=0x0a0a18:c1=0x2a1060:type=radial:speed=0.02,"
                f"sendcmd=f='{_ffmpeg_path(cmd_path)}',huesaturation"
            )
            mp4 = _render(Path(tmp) / "backdrop.mp4", vsrc)
            band = _luma_series(mp4, crop="crop=320:34:0:146")  # faixa da letra
            self.assertGreater(len(band), 0, "serie vazia nao e' aprovacao")
            self.assertEqual(60, len(band), "denominador: 2s x 30fps")
            self.assertLess(_delta(band), THRESHOLD_CDM2)

    def test_the_fence_goes_red_on_a_deliberate_strobe(self):
        # Controle negativo. Sem isto, o teste acima e' verde universal.
        with TemporaryDirectory() as tmp:
            mp4 = _render(
                Path(tmp) / "strobe.mp4",
                "nullsrc=s=320x180:r=30,geq=lum='if(lt(mod(T*30,2),1),235,16)':cb=128:cr=128",
            )
            series = _luma_series(mp4)
            self.assertEqual(60, len(series), "denominador: 2s x 30fps")
            self.assertGreaterEqual(
                _delta(series), THRESHOLD_CDM2,
                "a cerca nao detectou um estrobo — ela nao discrimina",
            )
