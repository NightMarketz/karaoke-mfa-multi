import tempfile
import unittest
from pathlib import Path, PurePosixPath

from scripts.common.paths import (
    is_safe_archive_member,
    resolve_job_dir,
    validate_job_id,
)


class SafePathTests(unittest.TestCase):
    def test_job_id_accepts_uuid_prefix_style(self):
        self.assertTrue(validate_job_id("abc123def456"))

    def test_job_id_rejects_traversal(self):
        self.assertFalse(validate_job_id("../jobs/test"))
        self.assertFalse(validate_job_id("abc/def"))
        self.assertFalse(validate_job_id(""))

    def test_archive_member_rejects_traversal(self):
        self.assertFalse(is_safe_archive_member("../vocals.wav"))
        self.assertFalse(is_safe_archive_member("nested/../../vocals.wav"))
        self.assertFalse(is_safe_archive_member("/absolute/vocals.wav"))

    def test_archive_member_allows_nested_audio(self):
        self.assertTrue(is_safe_archive_member("stems/vocals.wav"))
        self.assertTrue(
            is_safe_archive_member(str(PurePosixPath("Suno") / "instrumental.mp3"))
        )

    def test_resolve_job_dir_accepts_safe_id_under_jobs_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            expected = (jobs_dir / "abc123def456").resolve()
            self.assertEqual(resolve_job_dir(jobs_dir, "abc123def456"), expected)

    def test_resolve_job_dir_rejects_invalid_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                resolve_job_dir(Path(tmp), "../abc123def456")


if __name__ == "__main__":
    unittest.main()
