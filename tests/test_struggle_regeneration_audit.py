import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.common.provenance import file_sha256, write_manifest
from scripts import struggle_regeneration_audit as audit


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_valid_job(job_dir: Path) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    words = [
        {"word": "About", "start": 274.48, "end": 274.9},
        {"word": "to", "start": 274.92, "end": 275.15},
        {"word": "snap", "start": 275.42, "end": 282.02},
    ]
    analysis = {"lines": [{"text": "About to snap", "start": 274.48, "end": 282.02, "words": words}]}
    _write_json(job_dir / "analysis.json", analysis)
    ass_content = (
        "[Script Info]\n"
        "[Events]\n"
        "Dialogue: 0,0:04:34.48,0:04:42.02,Highlight,,0,0,0,,"
        "{\\kf42}About {\\kf23}to {\\kf16}sn{\\kf624}a{\\kf18}p\n"
    )
    (job_dir / "output.ass").write_text(ass_content, encoding="utf-8")
    (job_dir / "output.mp4").write_bytes(b"mp4-current")
    write_manifest(
        job_dir / "output.ass.manifest.json",
        {
            "stage": "stage06",
            "renderer_mode": "single_layer_kf",
            "inputs": {
                "analysis.json": {
                    "path": "analysis.json",
                    "sha256": file_sha256(job_dir / "analysis.json"),
                }
            },
            "metrics": {"dialogue_count": 1, "analysis_line_count": 1},
        },
        output_paths={"output.ass": job_dir / "output.ass"},
    )
    write_manifest(
        job_dir / "output.mp4.manifest.json",
        {
            "stage": "stage07",
            "inputs": {
                "output.ass": {
                    "path": "output.ass",
                    "sha256": file_sha256(job_dir / "output.ass"),
                }
            },
        },
        output_paths={"output.mp4": job_dir / "output.mp4"},
    )


class StruggleRegenerationAuditTests(unittest.TestCase):
    def test_discovers_struggle_jobs_under_jobs_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp)
            (jobs_root / "test-struggle").mkdir()
            (jobs_root / "Struggle Final").mkdir()
            (jobs_root / "other-song").mkdir()
            (jobs_root / "struggle-file").write_text("not a dir", encoding="utf-8")

            self.assertEqual(
                [path.name for path in audit.discover_struggle_jobs(jobs_root)],
                ["Struggle Final", "test-struggle"],
            )

    def test_cleanup_is_dry_by_default_and_scoped_to_derived_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_root = Path(tmp) / "jobs"
            job_dir = jobs_root / "test-struggle"
            job_dir.mkdir(parents=True)
            for name in audit.DERIVED_ARTIFACTS:
                (job_dir / name).write_text("derived", encoding="utf-8")
            (job_dir / "input.wav").write_text("source", encoding="utf-8")

            dry = audit.clean_derived_artifacts(job_dir, clean=False)
            self.assertEqual(sorted(dry), sorted(audit.DERIVED_ARTIFACTS))
            self.assertTrue((job_dir / "analysis.json").exists())
            self.assertTrue((job_dir / "input.wav").exists())

            with patch.object(audit, "JOBS_ROOT", jobs_root):
                cleaned = audit.clean_derived_artifacts(job_dir, clean=True)
            self.assertEqual(sorted(cleaned), sorted(audit.DERIVED_ARTIFACTS))
            self.assertFalse((job_dir / "analysis.json").exists())
            self.assertTrue((job_dir / "input.wav").exists())

    def test_builds_stage_05_06_07_commands_with_explicit_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            job_dir.mkdir()

            commands = audit.build_stage_commands(job_dir, preset="section-coded")

            self.assertEqual([command.stage for command in commands], ["stage05", "stage06", "stage07"])
            self.assertIn("--preset", commands[1].args)
            self.assertIn("section-coded", commands[1].args)
            self.assertTrue(commands[0].args[-1].endswith("test-struggle"))

    def test_build_stage_commands_passes_lyrics_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            job_dir.mkdir()
            lyrics = job_dir / "lyrics.txt"
            lyrics.write_text("About to snap", encoding="utf-8")

            commands = audit.build_stage_commands(job_dir, preset="section-coded")

            self.assertIn("--lyrics", commands[0].args)
            self.assertIn(str(lyrics), commands[0].args)

    def test_audits_valid_provenance_and_about_to_snap_golden(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)

            result = audit.audit_job(job_dir)

            self.assertTrue(result.ok, result.issues)
            self.assertIn("provenance", result.checks)
            self.assertIn("about_to_snap", result.checks)
            snap = result.checks["about_to_snap"]
            self.assertTrue(snap["ok"], snap)
            self.assertGreater(snap["sustained_vowel_duration_s"], 6.0)
            self.assertEqual(snap["expected_vowel_kf"], "\\kf624}a")

    def test_audit_rejects_stale_analysis_hash_and_legacy_base_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "About to snap", "words": []}]}),
                encoding="utf-8",
            )
            with (job_dir / "output.ass").open("a", encoding="utf-8") as handle:
                handle.write("Dialogue: 0,0:00:00.00,0:00:01.00,Base,,0,0,0,,bad\n")

            result = audit.audit_job(job_dir)

            self.assertFalse(result.ok)
            self.assertTrue(any("analysis.json hash" in issue for issue in result.issues))
            self.assertTrue(any("Base,," in issue for issue in result.issues))

    def test_audit_rejects_stale_ass_output_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            with (job_dir / "output.ass").open("a", encoding="utf-8") as handle:
                handle.write("Dialogue: 0,0:00:02.00,0:00:03.00,Highlight,,0,0,0,,changed\n")

            result = audit.audit_job(job_dir)

            self.assertFalse(result.ok)
            self.assertTrue(any("output.ass hash" in issue for issue in result.issues))

    def test_audit_rejects_stale_mp4_output_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            (job_dir / "output.mp4").write_bytes(b"changed mp4")

            result = audit.audit_job(job_dir)

            self.assertFalse(result.ok)
            self.assertTrue(any("output.mp4 hash" in issue for issue in result.issues))

    def test_audit_rejects_mp4_manifest_pointing_to_old_ass_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            mp4_manifest = json.loads(
                (job_dir / "output.mp4.manifest.json").read_text(encoding="utf-8")
            )
            mp4_manifest["inputs"]["output.ass"]["sha256"] = "0" * 64
            (job_dir / "output.mp4.manifest.json").write_text(
                json.dumps(mp4_manifest), encoding="utf-8"
            )

            result = audit.audit_job(job_dir)

            self.assertFalse(result.ok)
            self.assertTrue(
                any("does not reference current output.ass" in issue for issue in result.issues)
            )

    def test_audit_rejects_non_single_layer_renderer_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            ass_manifest = json.loads(
                (job_dir / "output.ass.manifest.json").read_text(encoding="utf-8")
            )
            ass_manifest["renderer_mode"] = "dual_layer_legacy"
            (job_dir / "output.ass.manifest.json").write_text(
                json.dumps(ass_manifest), encoding="utf-8"
            )

            result = audit.audit_job(job_dir)

            self.assertFalse(result.ok)
            self.assertTrue(any("renderer_mode" in issue for issue in result.issues))

    def test_audit_rejects_dialogue_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            analysis = json.loads((job_dir / "analysis.json").read_text(encoding="utf-8"))
            analysis["lines"].append({"text": "extra line", "words": []})
            (job_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
            ass_manifest = json.loads(
                (job_dir / "output.ass.manifest.json").read_text(encoding="utf-8")
            )
            ass_manifest["inputs"]["analysis.json"]["sha256"] = audit.file_sha256(
                job_dir / "analysis.json"
            )
            (job_dir / "output.ass.manifest.json").write_text(
                json.dumps(ass_manifest), encoding="utf-8"
            )

            result = audit.audit_job(job_dir)

            self.assertFalse(result.ok)
            self.assertTrue(any("dialogue count mismatch" in issue for issue in result.issues))

    def test_report_includes_status_cleaned_commands_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            result = audit.audit_job(job_dir)
            command = audit.StageCommand("stage06", [sys.executable, "scripts/s06_generate_ass.py"])
            result.cleaned_artifacts = ["output.ass"]
            result.commands = [audit.CommandResult(command=command, returncode=0)]

            audit.write_markdown_report(report, [result])

            content = report.read_text(encoding="utf-8")
            self.assertIn("# Struggle Regeneration Audit", content)
            self.assertIn("test-struggle", content)
            self.assertIn("Status: PASS", content)
            self.assertIn("output.ass", content)
            self.assertIn("stage06", content)
            self.assertIn("about_to_snap", content)

    def test_cli_does_not_run_commands_without_run_flag_and_can_fail_on_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            job_dir.mkdir()
            report = Path(tmp) / "report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/struggle_regeneration_audit.py",
                    "--job-dir",
                    str(job_dir),
                    "--report",
                    str(report),
                    "--fail-on-issues",
                ],
                cwd=Path(__file__).resolve().parent.parent,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(report.exists())
            self.assertIn("not run", report.read_text(encoding="utf-8").lower())

    def test_cli_rejects_clean_for_job_dir_outside_jobs_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "outside-struggle"
            job_dir.mkdir()
            (job_dir / "output.ass").write_text("must stay", encoding="utf-8")
            report = Path(tmp) / "report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/struggle_regeneration_audit.py",
                    "--job-dir",
                    str(job_dir),
                    "--clean",
                    "--report",
                    str(report),
                    "--fail-on-issues",
                ],
                cwd=Path(__file__).resolve().parent.parent,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((job_dir / "output.ass").exists())
            self.assertIn("outside jobs root", report.read_text(encoding="utf-8"))

    def test_command_failure_marks_job_failed_even_if_existing_artifacts_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            _write_valid_job(job_dir)
            result = audit.audit_job(job_dir)
            result.commands = [
                audit.CommandResult(
                    command=audit.StageCommand("stage05", [sys.executable, "missing.py"]),
                    returncode=2,
                )
            ]
            audit.apply_command_failures(result)

            self.assertFalse(result.ok)
            self.assertTrue(any("stage05 failed" in issue for issue in result.issues))

    def test_cli_dry_run_does_not_report_artifacts_as_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "test-struggle"
            job_dir.mkdir()
            (job_dir / "output.ass").write_text("derived", encoding="utf-8")
            report = Path(tmp) / "report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/struggle_regeneration_audit.py",
                    "--job-dir",
                    str(job_dir),
                    "--report",
                    str(report),
                ],
                cwd=Path(__file__).resolve().parent.parent,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((job_dir / "output.ass").exists())
            self.assertIn("Cleaned artifacts: none", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
