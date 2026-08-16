import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._optional_imports import import_or_skip

import_or_skip("flask")
import server


def _syl(sid, text, start, end, conf):
    return {"syllable_id": sid, "text": text, "karaoke_start": start,
            "karaoke_end": end, "confidence": conf}


class SyllableBrowseScopeTests(unittest.TestCase):
    def _write_job(self, job_dir: Path, job_id: str) -> None:
        job_dir.mkdir()
        (job_dir / "meta.json").write_text(json.dumps({"job_id": job_id, "song_name": "S"}), encoding="utf-8")
        (job_dir / "analysis.json").write_text(
            json.dumps({"lines": [{"id": "L001", "text": "l", "words": [
                # confident multi-syllable word (never flagged, but browsable)
                {"id": "W1", "word": "beneath", "start": 1.0, "end": 1.9, "syllables": [
                    _syl("s1", "be", 1.0, 1.4, 0.9), _syl("s2", "neath", 1.4, 1.9, 0.88)]},
                # uncertain multi-syllable word (flagged)
                {"id": "W2", "word": "beast", "start": 2.0, "end": 2.8, "syllables": [
                    _syl("s3", "be", 2.0, 2.4, 0.45), _syl("s4", "ast", 2.4, 2.8, 0.8)]},
                # single-syllable word (not browsable — no internal boundary)
                {"id": "W3", "word": "the", "start": 3.0, "end": 3.2, "syllables": [
                    _syl("s5", "the", 3.0, 3.2, 0.9)]},
            ]}]}),
            encoding="utf-8",
        )

    def test_default_scope_returns_only_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp); jid = "abc123def456"
            self._write_job(jobs / jid, jid)
            with patch.object(server, "JOBS_DIR", jobs):
                r = server.app.test_client().get(f"/job/{jid}/review/syllables/pending")
        p = r.get_json()
        self.assertEqual([w["word_text"] for w in p["pending"]], ["beast"])
        self.assertEqual(p["uncertain_count"], 1)

    def test_scope_all_returns_every_multisyllable_word_with_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp); jid = "abc123def456"
            self._write_job(jobs / jid, jid)
            with patch.object(server, "JOBS_DIR", jobs):
                r = server.app.test_client().get(f"/job/{jid}/review/syllables/pending?scope=all")
        p = r.get_json()
        words = {w["word_text"]: w["uncertain"] for w in p["pending"]}
        self.assertEqual(set(words), {"beneath", "beast"})   # 'the' (1 syllable) excluded
        self.assertFalse(words["beneath"])                    # confident, browsable
        self.assertTrue(words["beast"])                       # flagged
        self.assertEqual(p["scope"], "all")
        self.assertEqual(p["uncertain_count"], 1)


if __name__ == "__main__":
    unittest.main()
