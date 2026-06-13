import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from tests._optional_imports import import_or_skip

import_or_skip("numpy")

from scripts.common.provenance import file_sha256
from scripts import struggle_regeneration_audit as audit


PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_ROOT = PROJECT_ROOT / "jobs"


class CleanOutputsIntegrationTests(unittest.TestCase):
    def test_clean_run_creates_current_stage05_06_07_outputs_and_manifests(self):
        with tempfile.TemporaryDirectory(dir=JOBS_ROOT, prefix="clean-room-") as tmp:
            job_dir = Path(tmp)
            self._write_forced_alignment_inputs(job_dir)
            self._write_audio(job_dir / "instrumental.wav", duration_s=8.0)
            self._write_audio(job_dir / "vocals.wav", duration_s=8.0)
            self._write_stale_derived_outputs(job_dir)
            report_path = job_dir / "clean-report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/struggle_regeneration_audit.py",
                    "--job-dir",
                    str(job_dir),
                    "--clean",
                    "--run",
                    "--fail-on-issues",
                    "--report",
                    str(report_path),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=180,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in (
                "analysis.json",
                "output.ass",
                "output.ass.manifest.json",
                "output.mp4",
                "output.mp4.manifest.json",
            ):
                path = job_dir / name
                self.assertTrue(path.exists(), name)
                self.assertGreater(path.stat().st_size, 0, name)

            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            ass_manifest = json.loads(
                (job_dir / "output.ass.manifest.json").read_text(encoding="utf-8")
            )
            mp4_manifest = json.loads(
                (job_dir / "output.mp4.manifest.json").read_text(encoding="utf-8")
            )
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            report = report_path.read_text(encoding="utf-8")

            self.assertEqual(len(analysis["lines"]), 1)
            self.assertEqual(ass_manifest["renderer_mode"], "single_layer_kf")
            self.assertEqual(
                ass_manifest["inputs"]["analysis.json"]["sha256"],
                file_sha256(job_dir / "analysis.json"),
            )
            self.assertEqual(
                ass_manifest["outputs"]["output.ass"]["sha256"],
                file_sha256(job_dir / "output.ass"),
            )
            self.assertEqual(
                mp4_manifest["inputs"]["output.ass"]["sha256"],
                file_sha256(job_dir / "output.ass"),
            )
            self.assertEqual(
                mp4_manifest["outputs"]["output.mp4"]["sha256"],
                file_sha256(job_dir / "output.mp4"),
            )
            self.assertIn("\\kf624}a", ass_content)
            self.assertNotIn("stale", ass_content)
            self.assertIn("Status: PASS", report)

            audit_result = audit.audit_job(job_dir)
            self.assertTrue(audit_result.ok, audit_result.issues)

    def test_clean_run_with_real_struggle_inputs_creates_current_outputs(self):
        fixture_dir = JOBS_ROOT / "real-struggle-20260522"
        required_inputs = (
            "transcript.json",
            "aligned.json",
            "lyrics.txt",
            "instrumental.wav",
            "vocals.wav",
        )
        missing = [name for name in required_inputs if not (fixture_dir / name).exists()]
        if missing:
            self.skipTest(f"real Struggle fixture missing inputs: {missing}")

        with tempfile.TemporaryDirectory(dir=JOBS_ROOT, prefix="real-struggle-clean-") as tmp:
            job_dir = Path(tmp)
            for name in required_inputs:
                shutil.copy2(fixture_dir / name, job_dir / name)
            self._write_stale_derived_outputs(job_dir)
            report_path = job_dir / "clean-report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/struggle_regeneration_audit.py",
                    "--job-dir",
                    str(job_dir),
                    "--clean",
                    "--run",
                    "--fail-on-issues",
                    "--report",
                    str(report_path),
                ],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=240,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            ass_manifest = json.loads(
                (job_dir / "output.ass.manifest.json").read_text(encoding="utf-8")
            )
            mp4_manifest = json.loads(
                (job_dir / "output.mp4.manifest.json").read_text(encoding="utf-8")
            )
            ass_content = (job_dir / "output.ass").read_text(encoding="utf-8-sig")
            report = report_path.read_text(encoding="utf-8")

            self.assertEqual(len(analysis["lines"]), 79)
            self.assertEqual(ass_manifest["renderer_mode"], "single_layer_kf")
            self.assertEqual(ass_manifest["metrics"]["dialogue_count"], 79)
            self.assertEqual(
                ass_manifest["inputs"]["analysis.json"]["sha256"],
                file_sha256(job_dir / "analysis.json"),
            )
            self.assertEqual(
                ass_manifest["outputs"]["output.ass"]["sha256"],
                file_sha256(job_dir / "output.ass"),
            )
            self.assertEqual(
                mp4_manifest["inputs"]["output.ass"]["sha256"],
                file_sha256(job_dir / "output.ass"),
            )
            self.assertEqual(
                mp4_manifest["outputs"]["output.mp4"]["sha256"],
                file_sha256(job_dir / "output.mp4"),
            )
            self.assertIn("\\kf624}a", ass_content)
            self.assertIn("Status: PASS", report)

            audit_result = audit.audit_job(job_dir)
            self.assertTrue(audit_result.ok, audit_result.issues)

    def _write_forced_alignment_inputs(self, job_dir: Path) -> None:
        words = [
            {"word": "About", "start": 0.2, "end": 0.6, "source": "ctc_forced"},
            {"word": "to", "start": 0.7, "end": 0.9, "source": "ctc_forced"},
            {"word": "snap", "start": 1.0, "end": 7.6, "source": "ctc_forced"},
        ]
        transcript = {
            "language": "en",
            "alignment_mode": "forced",
            "segments": [
                {
                    "text": "About to snap",
                    "start": 0.2,
                    "end": 7.6,
                    "section": "verse",
                    "words": words,
                }
            ],
        }
        (job_dir / "transcript.json").write_text(
            json.dumps(transcript), encoding="utf-8"
        )
        (job_dir / "aligned.json").write_text(
            json.dumps({"words": words}), encoding="utf-8"
        )
        (job_dir / "lyrics.txt").write_text("About to snap\n", encoding="utf-8")

    def _write_stale_derived_outputs(self, job_dir: Path) -> None:
        (job_dir / "analysis.json").write_text("stale analysis", encoding="utf-8")
        (job_dir / "output.ass").write_text("stale ass", encoding="utf-8")
        (job_dir / "output.ass.manifest.json").write_text("{}", encoding="utf-8")
        (job_dir / "output.mp4").write_bytes(b"stale mp4")
        (job_dir / "output.mp4.manifest.json").write_text("{}", encoding="utf-8")

    def _write_audio(self, path: Path, *, duration_s: float) -> None:
        sample_rate = 16_000
        frames = int(sample_rate * duration_s)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            for index in range(frames):
                value = int(1000 * math.sin(2 * math.pi * 220 * index / sample_rate))
                handle.writeframes(struct.pack("<h", value))


if __name__ == "__main__":
    unittest.main()
