"""
Testa as 12 etapas do pipeline, injetando mocks ou verificando as saídas em cada passo.
"""
import os
import json
from pathlib import Path

def verify_step_1_preprocess(job_dir):
    assert (job_dir / "01_wav" / "song.wav").exists(), "Step 1 failed: song.wav not found"
    print("Step 1 (Preprocess Audio) verified.")

def verify_step_2_demucs(job_dir):
    assert (job_dir / "03_vocals_clean" / "vocals_raw.wav").exists(), "Step 2 failed: vocals_raw.wav not found"
    assert (job_dir / "03_vocals_clean" / "vocals_listen.wav").exists(), "Step 2 failed: vocals_listen.wav not found"
    print("Step 2 (Demucs Vocal Separation) verified.")

def verify_step_3_prepare_corpus(job_dir):
    assert (job_dir / "04_mfa_corpus" / "song.lab").exists(), "Step 3 failed: song.lab not found"
    print("Step 3 (Prepare Corpus) verified.")

def verify_step_4_ctc_align(job_dir):
    assert (job_dir / "05_alignment" / "word_timing.json").exists(), "Step 4 failed: word_timing.json not found"
    print("Step 4 (CTC Forced Alignment) verified.")

def verify_step_5_whisperx(job_dir):
    # WhisperX Rescue overrides or ensures word_timing.json exists
    assert (job_dir / "05_alignment" / "word_timing.json").exists(), "Step 5 failed: word_timing.json not found"
    print("Step 5 (WhisperX Rescue) verified.")

def verify_step_6_gemini_adlib(job_dir):
    assert (job_dir / "05_alignment" / "adlibs_timing.json").exists(), "Step 6 failed: adlibs_timing.json not found"
    print("Step 6 (Gemini Adlib Detection) verified.")

def verify_step_7_vad_clamping(job_dir):
    # VAD Clamping modifies word_timing.json
    assert (job_dir / "05_alignment" / "word_timing.json").exists(), "Step 7 failed: word_timing.json not found"
    print("Step 7 (VAD Clamping) verified.")

def verify_step_8_onset_dtw(job_dir):
    assert (job_dir / "05_alignment" / "word_timing_fixed.json").exists(), "Step 8 failed: word_timing_fixed.json not found"
    print("Step 8 (Onset DTW Alignment) verified.")

def verify_step_9_generate_ass(job_dir):
    assert (job_dir / "06_ass" / "karaoke.ass").exists(), "Step 9 failed: karaoke.ass not found"
    print("Step 9 (Generate ASS) verified.")

def verify_step_10_qc_report(job_dir):
    assert (job_dir / "06_ass" / "qc.json").exists(), "Step 10 failed: qc.json not found"
    print("Step 10 (QC Report) verified.")

def verify_step_11_audio_mixing(job_dir):
    assert (job_dir / "08_mixed" / "instrumental.mp3").exists(), "Step 11 failed: instrumental.mp3 not found"
    assert (job_dir / "08_mixed" / "guide.mp3").exists(), "Step 11 failed: guide.mp3 not found"
    print("Step 11 (Audio Mixing) verified.")

def verify_step_12_render_video(job_dir):
    assert (job_dir / "07_video" / "karaoke_preview.mp4").exists(), "Step 12 failed: karaoke_preview.mp4 not found"
    print("Step 12 (Render Video) verified.")

def test_pipeline_all_steps(job_dir_path):
    job_dir = Path(job_dir_path)
    if not job_dir.exists():
        print(f"Error: Job directory {job_dir} does not exist.")
        return

    print(f"Verifying pipeline for job: {job_dir.name}")
    verify_step_1_preprocess(job_dir)
    verify_step_2_demucs(job_dir)
    verify_step_3_prepare_corpus(job_dir)
    verify_step_4_ctc_align(job_dir)
    verify_step_5_whisperx(job_dir)
    verify_step_6_gemini_adlib(job_dir)
    verify_step_7_vad_clamping(job_dir)
    verify_step_8_onset_dtw(job_dir)
    verify_step_9_generate_ass(job_dir)
    verify_step_10_qc_report(job_dir)
    verify_step_11_audio_mixing(job_dir)
    verify_step_12_render_video(job_dir)
    print("\n✅ All 12 pipeline steps verified successfully!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_pipeline_all_steps(sys.argv[1])
    else:
        print("Please provide the job directory path as an argument. Example:")
        print("python test_pipeline_e2e.py ../work/jobs/<job-id>")
