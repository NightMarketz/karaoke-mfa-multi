import os
import json
import pytest
from karaoke import resume_planner, state_store

def test_job_id_consistency(tmp_path):
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"dummy audio content")
    
    lyrics = "Test lyrics content"
    lang = "pt"
    config = {"mfa_lang": "pt"}
    
    id1 = resume_planner.calculate_job_id(str(audio), lyrics, lang, config)
    id2 = resume_planner.calculate_job_id(str(audio), lyrics, lang, config)
    
    assert id1 == id2
    
    # Change lyrics and verify ID changes
    id3 = resume_planner.calculate_job_id(str(audio), "Different lyrics", lang, config)
    assert id1 != id3

def test_resume_planning(tmp_path):
    # Setup dummy job data as it would look in state.json
    job_id = "test_job"
    audio_wav = tmp_path / "song.wav"
    audio_wav.write_bytes(b"wav content")
    
    job_data = {
        "job_id": job_id,
        "steps": {
            "Step 1": {
                "status": "ok",
                "outputs": {"wav": str(audio_wav)}
            },
            "Step 2": {
                "status": "fail",
                "outputs": {}
            }
        }
    }
    
    current_steps = [
        {"name": "Step 1", "outputs": {"wav": str(audio_wav)}},
        {"name": "Step 2", "outputs": {}},
        {"name": "Step 3", "outputs": {}}
    ]
    
    # Verify Step 1 is skipped
    skips = resume_planner.get_resume_plan(job_data, current_steps)
    assert skips == ["Step 1"]
    
    # Verify if file is missing, Step 1 is NOT skipped
    audio_wav.unlink()
    skips_missing = resume_planner.get_resume_plan(job_data, current_steps)
    assert skips_missing == []

def test_validate_outputs(tmp_path):
    f1 = tmp_path / "f1.txt"
    f1.write_text("hello")
    
    assert resume_planner.validate_step_outputs({"file": str(f1)}) is True
    assert resume_planner.validate_step_outputs({"file": str(tmp_path / "missing.txt")}) is False
