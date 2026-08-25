import os
from pathlib import Path

# --- Installation Paths (User Specific) ---
# These point to the external SOFA and ROSVOT installations
SOFA_INST_DIR = Path(r"C:\Users\Lu\Documents\sofa")
ROSVOT_INST_DIR = Path(r"C:\Users\Lu\Documents\ROSVOT")
CHECKPOINT_ROSVOT = ROSVOT_INST_DIR / "rosvot.ckpt"

def repos_root() -> Path:
    """Returns the absolute path to the repository root."""
    return Path(__file__).resolve().parent.parent

def job_root(job_id: str) -> Path:
    """The root directory for a specific job (absolute)."""
    return repos_root() / "work" / "jobs" / job_id

def input_dir(job_id: str) -> Path:
    """Where raw input files (audio, lyrics) are stored."""
    return job_root(job_id) / "input"

def song_mp3(job_id: str) -> Path:
    """Raw song file."""
    return input_dir(job_id) / "song.mp3"

def lyrics_path(job_id: str) -> Path:
    """Raw lyrics file. Stored in job/input/lyrics.txt."""
    return input_dir(job_id) / "lyrics.txt"

def step_output(job_id: str, step_name: str) -> Path:
    """Base directory for a specific pipeline step's output."""
    return job_root(job_id) / step_name

# --- Specific Step Accessors ---

def lyrics_dir(job_id: str) -> Path:
    """Step 01 - Original or extracted lyrics."""
    return step_output(job_id, "01_lyrics")

def separation_dir(job_id: str) -> Path:
    """Onde o Demucs salva os stems."""
    return job_root(job_id) / "02_separation"

def vocals_raw(job_id: str) -> Path:
    """Voz isolada vinda do Demucs (copiada para cá para simplificar)."""
    return separation_dir(job_id) / "vocals.wav"

# --- MFA ---
def mfa_corpus_dir(job_id: str) -> Path:
    return job_root(job_id) / "04_mfa_corpus"

def corpus_dir(job_id: str) -> Path:
    """Corpus .lab que o MFA consome. Alias de mfa_corpus_dir — confirmado
    que quem grava (03_prepare_corpus.py) e quem le (04_mfa_alignment.py)
    usam o mesmo diretorio 04_mfa_corpus."""
    return mfa_corpus_dir(job_id)

def mfa_textgrid(job_id: str) -> Path:
    """TextGrid gerado pelo MFA."""
    return job_root(job_id) / "05_alignment" / "mfa_vocals.TextGrid"

# --- SOFA / ROSVOT ---
def sofa_dir(job_id: str) -> Path:
    return job_root(job_id) / "03_sofa"

def sofa_textgrid(job_id: str) -> Path:
    return sofa_dir(job_id) / "sofa.TextGrid"

def rosvot_dir(job_id: str) -> Path:
    return job_root(job_id) / "03_rosvot"

def rosvot_json(job_id: str) -> Path:
    return rosvot_dir(job_id) / "rosvot.json"

def fused_alignment_json(job_id: str) -> Path:
    return job_root(job_id) / "05_alignment" / "fused_alignment.json"

# --- ALIGNMENT OUTPUTS ---
def alignment_dir(job_id: str) -> Path:
    return job_root(job_id) / "05_alignment"

def vocals_clean_dir(job_id: str) -> Path:
    """Step 03 - Vocal cleaning and normalization."""
    return step_output(job_id, "03_vocals_clean")

# --- OTHER STEPS ---
def rescue_dir(job_id: str) -> Path:
    """Step 06 - WhisperX rescue alignment."""
    return step_output(job_id, "06_rescue")

def transcription_dir(job_id: str) -> Path:
    """Step 07 - Gemini/Transcription enrichment."""
    return step_output(job_id, "07_transcription")

def ass_dir(job_id: str) -> Path:
    """Step 08 - Karaoke ASS generation."""
    return step_output(job_id, "08_ass")

def final_ass(job_id: str) -> Path:
    return ass_dir(job_id) / "lyrics.ass"

def refinement_dir(job_id: str) -> Path:
    """Step 09 - DTW/Onset refinement."""
    return step_output(job_id, "09_refinement")

def render_dir(job_id: str) -> Path:
    """Step 10 - Final video render."""
    return step_output(job_id, "10_render")

def final_video(job_id: str) -> Path:
    return render_dir(job_id) / "output_karaoke.mp4"

def cleanup_dir(job_id: str) -> Path:
    """Step 11 - Temporary files disposal."""
    return step_output(job_id, "11_cleanup")

def notification_dir(job_id: str) -> Path:
    """Step 12 - Reporting and external notifications."""
    return step_output(job_id, "12_notification")

def closure_dir(job_id: str) -> Path:
    """Step 13 - Finalizing and job archival."""
    return step_output(job_id, "13_final")

# --- Helper Accessors ---

def vocals_listen(job_id: str) -> Path:
    """Vocal file for final mixing (cleaned)."""
    return vocals_clean_dir(job_id) / "vocals_cleaned.wav"

def word_timing_json(job_id: str) -> Path:
    """Consolidated word-level timing results."""
    return alignment_dir(job_id) / "word_timing.json"

def unmapped_regions_json(job_id: str) -> Path:
    return alignment_dir(job_id) / "unmapped_regions.json"

def char_timing_json(job_id: str) -> Path:
    """Timing por caractere do CTC. Gravado por 03_forced_align.py:138."""
    return alignment_dir(job_id) / "char_timing.json"

# --- Render / fundo ---

def adlibs_json(job_id: str) -> Path:
    """Timings de adlibs gerados pelo Step 03c/07."""
    return alignment_dir(job_id) / "adlibs_timing.json"

def input_job_dir(job_id: str) -> Path:
    """Diretorio de input real do job (onde song.wav e escrito por
    01_media_prep.py e lido por 02_vocal_isolation.py/13_process_conclusion.py).
    Alias de input_dir — nao confundir com demucs_out_dir."""
    return input_dir(job_id)

def demucs_out_dir(job_id: str) -> Path:
    """Pasta que o Demucs cria para este job: htdemucs/<stem do audio>/.
    O Demucs nomeia a subpasta pelo stem do arquivo de entrada (song.wav),
    nao pelo diretorio de input — ver scripts/02_vocal_isolation.py."""
    return separation_dir(job_id) / "htdemucs" / "song"

def input_video(job_id: str) -> Path:
    """Video de fundo fornecido pelo usuario (opcional)."""
    return input_dir(job_id) / "background.mp4"

def input_thumb(job_id: str) -> Path:
    """Imagem de fundo fornecida pelo usuario (opcional)."""
    return input_dir(job_id) / "background.png"

def background_png(job_id: str) -> Path:
    """Ilustracao gerada pelo Step 08b."""
    return step_output(job_id, "08_background") / "background.png"

def output_video(job_id: str) -> Path:
    """MP4 final. Alias do final_video ja existente."""
    return final_video(job_id)
