from pathlib import Path

def job_root(job_id: str) -> Path:
    """The root directory for a specific job."""
    return Path("work/jobs") / job_id

def input_dir(job_id: str) -> Path:
    """Where raw input files (audio, lyrics) are stored."""
    return job_root(job_id) / "input"

def song_mp3(job_id: str) -> Path:
    """Raw song file."""
    return input_dir(job_id) / "song.mp3"

def lyrics_path(job_id: str) -> Path:
    """Raw lyrics file."""
    return input_dir(job_id) / "lyrics.txt"

def step_output(job_id: str, step_name: str) -> Path:
    """Base directory for a specific pipeline step's output."""
    return job_root(job_id) / step_name

# --- Specific Step Accessors ---

def wav_dir(job_id: str) -> Path:
    return step_output(job_id, "01_wav")

def song_wav(job_id: str) -> Path:
    return wav_dir(job_id) / "song.wav"

def separation_dir(job_id: str) -> Path:
    return step_output(job_id, "02_separation")

def vocals_raw(job_id: str) -> Path:
    """Mono 16k wav for CTC/WhisperX alignment."""
    return separation_dir(job_id) / "vocals_raw.wav"

def vocals_listen(job_id: str) -> Path:
    """Cleaned stereo 44k wav for final rendering."""
    return separation_dir(job_id) / "vocals_listen.wav"

def corpus_dir(job_id: str) -> Path:
    return step_output(job_id, "03_corpus")

def alignment_dir(job_id: str) -> Path:
    return step_output(job_id, "05_alignment")

def word_timing_json(job_id: str) -> Path:
    """Consolidated word-level timing results."""
    return alignment_dir(job_id) / "word_timing.json"

def adlibs_json(job_id: str) -> Path:
    """Ad-lib timing detected via Gemini/VAD."""
    return alignment_dir(job_id) / "adlibs_timing.json"

def unmapped_regions_json(job_id: str) -> Path:
    """Regions where VAD saw voice but MFA/Whisper saw no words."""
    return alignment_dir(job_id) / "unmapped_regions.json"

def whisperx_dir(job_id: str) -> Path:
    return step_output(job_id, "03_whisperx")

def gemini_dir(job_id: str) -> Path:
    return step_output(job_id, "04_gemini")

def sofa_dir(job_id: str) -> Path:
    return step_output(job_id, "03_sofa")

def sofa_textgrid(job_id: str) -> Path:
    return sofa_dir(job_id) / "alignment.TextGrid"

def rosvot_dir(job_id: str) -> Path:
    return step_output(job_id, "04_rosvot")

def rosvot_json(job_id: str) -> Path:
    return rosvot_dir(job_id) / "output.json"

def fusion_dir(job_id: str) -> Path:
    return step_output(job_id, "05_fusion")

def fused_midi(job_id: str) -> Path:
    return fusion_dir(job_id) / "fused_sofa_rosvot.mid"

def ass_dir(job_id: str) -> Path:
    return step_output(job_id, "06_ass")

def final_ass(job_id: str) -> Path:
    return ass_dir(job_id) / "lyrics.ass"

def qc_dir(job_id: str) -> Path:
    return step_output(job_id, "07_qc")

def mixing_dir(job_id: str) -> Path:
    return step_output(job_id, "08_mixing")

def final_audio(job_id: str) -> Path:
    return mixing_dir(job_id) / "final_mixed.wav"

def render_dir(job_id: str) -> Path:
    return step_output(job_id, "09_render")

def final_video(job_id: str) -> Path:
    return render_dir(job_id) / "output_karaoke.mp4"
