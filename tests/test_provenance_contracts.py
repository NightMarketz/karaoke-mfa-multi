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


class ProvenanceEdgeCaseTests(unittest.TestCase):
    def test_load_manifest_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.manifest.json"
            path.write_bytes(b"")
            with self.assertRaises(ProvenanceError):
                load_manifest(path)

    def test_load_manifest_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.manifest.json"
            path.write_text("not-json{", encoding="utf-8")
            with self.assertRaises(ProvenanceError):
                load_manifest(path)

    def test_load_manifest_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.manifest.json"
            path.write_text("[1,2,3]", encoding="utf-8")
            with self.assertRaises(ProvenanceError):
                load_manifest(path)

    def test_load_manifest_returns_dict_on_valid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "valid.manifest.json"
            path.write_text('{"stage": "s06"}', encoding="utf-8")
            result = load_manifest(path)
            self.assertEqual(result, {"stage": "s06"})

    def test_validate_file_hash_passes_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.bin"
            path.write_bytes(b"hello karaoke")
            digest = file_sha256(path)
            validate_file_hash(path, digest)  # should not raise

    def test_validate_file_hash_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.bin"
            with self.assertRaises(ProvenanceError):
                validate_file_hash(path, "a" * 64)

    def test_validate_file_hash_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.bin"
            path.write_bytes(b"")
            with self.assertRaises(ProvenanceError):
                validate_file_hash(path, "a" * 64)

    def test_write_manifest_sets_created_at_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "out.manifest.json"
            write_manifest(manifest_path, {"stage": "s06"})
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIsInstance(data["created_at"], float)
            self.assertGreater(data["created_at"], 0)

    def test_write_manifest_does_not_overwrite_existing_created_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "out.manifest.json"
            write_manifest(manifest_path, {"stage": "s06", "created_at": 12345.0})
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["created_at"], 12345.0)

    def test_write_manifest_without_output_paths_writes_no_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "out.manifest.json"
            write_manifest(manifest_path, {"stage": "s06"})
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("sha256", data)

    def test_write_manifest_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "out.manifest.json"
            result = write_manifest(manifest_path, {"stage": "s06"})
            self.assertEqual(result, manifest_path)

    def test_file_sha256_different_content_different_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "a.bin"
            path_b = Path(tmp) / "b.bin"
            path_a.write_bytes(b"content-alpha")
            path_b.write_bytes(b"content-beta")
            self.assertNotEqual(file_sha256(path_a), file_sha256(path_b))
