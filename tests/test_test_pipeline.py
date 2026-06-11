import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import test_pipeline


class TestPipelineIntegrationHelpers(unittest.TestCase):
    def test_resolve_stage06_preset_prefers_meta_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "meta.json").write_text(
                json.dumps({"preset": "highlight"}), encoding="utf-8"
            )
            pipeline_toml = job_dir / "pipeline.toml"
            pipeline_toml.write_text('[generate]\nstyle_preset = "default"\n', encoding="utf-8")

            self.assertEqual(
                "highlight",
                test_pipeline.resolve_stage06_preset(job_dir, pipeline_toml),
            )

    def test_resolve_stage06_preset_falls_back_to_pipeline_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            pipeline_toml = job_dir / "pipeline.toml"
            pipeline_toml.write_text('[generate]\nstyle_preset = "section-coded"\n', encoding="utf-8")

            self.assertEqual(
                "section-coded",
                test_pipeline.resolve_stage06_preset(job_dir, pipeline_toml),
            )

    def test_resolve_stage06_preset_defaults_to_single_style_kf(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            self.assertEqual(
                "single-style-kf",
                test_pipeline.resolve_stage06_preset(job_dir, job_dir / "missing.toml"),
            )

    def test_build_stage06_args_passes_explicit_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            (job_dir / "meta.json").write_text(
                json.dumps({"preset": "single-style"}), encoding="utf-8"
            )

            args = test_pipeline.build_stage06_args(job_dir, job_dir / "missing.toml")

            self.assertEqual(
                ["--job-dir", str(job_dir), "--preset", "single-style"],
                args,
            )

    def test_validate_integration_provenance_accepts_current_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_valid_graph(job_dir)

            self.assertTrue(self._validate_graph_silently(job_dir))

    def test_validate_integration_provenance_rejects_stale_mp4_ass_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_valid_graph(job_dir)
            mp4_manifest = json.loads(
                (job_dir / "output.mp4.manifest.json").read_text(encoding="utf-8")
            )
            mp4_manifest["inputs"]["output.ass"]["sha256"] = "0" * 64
            (job_dir / "output.mp4.manifest.json").write_text(
                json.dumps(mp4_manifest), encoding="utf-8"
            )

            self.assertFalse(self._validate_graph_silently(job_dir))

    def test_validate_integration_provenance_rejects_stale_analysis_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_valid_graph(job_dir)
            (job_dir / "analysis.json").write_text(
                json.dumps({"lines": [{"text": "changed", "style": "verse"}]}),
                encoding="utf-8",
            )

            self.assertFalse(self._validate_graph_silently(job_dir))

    def test_validate_integration_provenance_rejects_missing_analysis_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_valid_graph(job_dir)
            ass_manifest = json.loads(
                (job_dir / "output.ass.manifest.json").read_text(encoding="utf-8")
            )
            ass_manifest["inputs"] = {}
            (job_dir / "output.ass.manifest.json").write_text(
                json.dumps(ass_manifest), encoding="utf-8"
            )

            self.assertFalse(self._validate_graph_silently(job_dir))

    def test_validate_integration_provenance_rejects_base_dialogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            self._write_valid_graph(job_dir, ass_body="Dialogue: 0,0:00:00.00,0:00:01.00,VerseBase,,0,0,0,,x\n")

            self.assertFalse(self._validate_graph_silently(job_dir))

    def _validate_graph_silently(self, job_dir: Path) -> bool:
        with contextlib.redirect_stdout(io.StringIO()):
            return test_pipeline.validate_integration_provenance(job_dir)

    def _write_valid_graph(self, job_dir: Path, ass_body: str | None = None) -> None:
        analysis = {"lines": [{"text": "about to snap", "style": "verse"}]}
        (job_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
        ass = "[Script Info]\n[V4+ Styles]\n[Events]\n"
        ass += ass_body or "Dialogue: 0,0:00:00.00,0:00:01.00,Verse,,0,0,0,,{\\kf100}about\n"
        (job_dir / "output.ass").write_text(ass, encoding="utf-8")
        (job_dir / "output.mp4").write_bytes(b"fake mp4 bytes")

        ass_sha = test_pipeline.file_sha256(job_dir / "output.ass")
        analysis_sha = test_pipeline.file_sha256(job_dir / "analysis.json")
        mp4_sha = test_pipeline.file_sha256(job_dir / "output.mp4")
        (job_dir / "output.ass.manifest.json").write_text(
            json.dumps(
                {
                    "stage": "stage06",
                    "inputs": {"analysis.json": {"sha256": analysis_sha}},
                    "outputs": {"output.ass": {"sha256": ass_sha}},
                    "metrics": {"dialogue_count": 1, "analysis_line_count": 1},
                }
            ),
            encoding="utf-8",
        )
        (job_dir / "output.mp4.manifest.json").write_text(
            json.dumps(
                {
                    "stage": "stage07",
                    "inputs": {"output.ass": {"sha256": ass_sha}},
                    "outputs": {"output.mp4": {"sha256": mp4_sha}},
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
