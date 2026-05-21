import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import server


class ServerContractTests(unittest.TestCase):
    def test_extract_suno_zip_rejects_traversal_member(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zf:
            zf.writestr("nested/../../vocals.wav", b"fake vocal")
            zf.writestr("instrumental.wav", b"fake instrumental")
        data.seek(0)

        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)

            vocals, instrumental = server._extract_suno_zip(data, job_dir)

            self.assertIsNone(vocals)
            self.assertIsNone(instrumental)
            self.assertFalse((job_dir / "stems" / "vocals.wav").exists())

    def test_delete_running_job_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_id = "abc123def456"
            job_dir = jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / "meta.json").write_text("{}", encoding="utf-8")

            with patch.object(server, "JOBS_DIR", jobs_dir), patch.dict(
                server._running, {job_id: object()}, clear=True
            ):
                response = server.app.test_client().post(f"/job/{job_id}/delete")

            self.assertEqual(response.status_code, 409)
            self.assertTrue(job_dir.exists())


if __name__ == "__main__":
    unittest.main()
