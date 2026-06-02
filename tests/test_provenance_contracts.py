import json
import tempfile
import unittest
from pathlib import Path

from scripts.common.provenance import (
    ProvenanceError,
    file_sha256,
    load_manifest,
    validate_file_hash,
    write_manifest,
)


class ProvenanceContractsTests(unittest.TestCase):
    def test_file_sha256_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.txt"
            path.write_text("karaoke", encoding="utf-8")
            self.assertEqual(file_sha256(path), file_sha256(path))
            self.assertEqual(len(file_sha256(path)), 64)

    def test_write_manifest_records_output_hash_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            artifact = job_dir / "output.ass"
            artifact.write_text("[Script Info]\n", encoding="utf-8")
            manifest_path = write_manifest(
                job_dir / "output.ass.manifest.json",
                {
                    "stage": "stage06",
                    "run_id": "run-test",
                    "outputs": {"output.ass": {"path": "output.ass"}},
                },
                output_paths={"output.ass": artifact},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["outputs"]["output.ass"]["sha256"], file_sha256(artifact)
            )
            self.assertEqual(
                manifest["outputs"]["output.ass"]["size_bytes"], artifact.stat().st_size
            )

    def test_validate_file_hash_rejects_changed_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output.ass"
            path.write_text("v1", encoding="utf-8")
            digest = file_sha256(path)
            path.write_text("v2", encoding="utf-8")
            with self.assertRaises(ProvenanceError):
                validate_file_hash(path, digest)

    def test_load_manifest_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProvenanceError):
                load_manifest(Path(tmp) / "missing.manifest.json")
