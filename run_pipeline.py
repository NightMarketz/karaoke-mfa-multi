import argparse
import os
import sys
import uuid
import subprocess
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

import karaoke.state_store as state_store
import karaoke.resume_planner as resume_planner
import karaoke.paths as kpaths

# Force UTF-8 for all child processes
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

def _p(*parts) -> str:
    return str(Path(*parts).resolve())

def run_command(cmd, shell=False):
    """Executes a command and returns return code, streaming output in real-time."""
    try:
        process = subprocess.Popen(
            cmd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1 # Line buffered
        )
        
        # We want to catch \r for progress bars
        while True:
            # Read character by character to handle \r
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            if char:
                sys.stdout.write(char)
                sys.stdout.flush()
        
        process.wait()
        return process.returncode
    except Exception as e:
        print(f"\n[ERROR] Exception during execution: {e}")
        return 1

def build_steps(job_id, lang, romanization, aligner="mfa"):
    python = sys.executable
    
    steps = [
        {
            "id": 1, "name": "Media Prep",
            "cmd": [python, _p("scripts", "01_media_prep.py"), "--job-id", job_id]
        },
        {
            "id": 2, "name": "Vocal Isolation",
            "cmd": [python, _p("scripts", "02_vocal_isolation.py"), "--job-id", job_id]
        },
        {
            "id": 3, "name": "Vocal Cleaning",
            "cmd": [python, _p("scripts", "03_vocal_cleaning.py"), "--job-id", job_id]
        }
    ]

    # --- ALIGNMENT PATH ---
    if aligner == "mfa":
        steps.extend([
            {
                "id": 4, "name": "MFA Corpus Prep",
                "cmd": [python, _p("scripts", "03_prepare_corpus.py"), "--job-id", job_id]
            },
            {
                "id": 5, "name": "MFA Alignment",
                "cmd": [python, _p("scripts", "04_mfa_alignment.py"), "--job-id", job_id,
                        "--lang", lang]
            },
            {
                "id": 6, "name": "Convert MFA to JSON",
                "cmd": [python, _p("scripts", "05_mfa_to_json.py"), "--job-id", job_id]
            }
        ])
    else: # SOFA / ROSVOT
        steps.extend([
            {
                "id": 4, "name": "SOFA Alignment",
                "cmd": [python, _p("scripts", "03_forced_align_sofa.py"), "--job-id", job_id]
            },
            {
                "id": 5, "name": "ROSVOT Inference",
                "cmd": [python, _p("scripts", "03b_rosvot_inference.py"), "--job-id", job_id]
            },
            {
                "id": 6, "name": "Fuse SOFA/ROSVOT",
                "cmd": [python, _p("scripts", "fuse_sofa_rosvot.py"), "--job-id", job_id]
            }
        ])

    # --- POST-ALIGNMENT / RESCUE ---
    steps.extend([
        {
            "id": 7, "name": "Gap Analysis & Sync",
            "cmd": [python, _p("scripts", "05_gap_analysis.py"), "--job-id", job_id]
        },
        {
            "id": 8, "name": "Alignment Rescue",
            "cmd": [python, _p("scripts", "06_alignment_rescue.py"), "--job-id", job_id]
        },
        {
            "id": 9, "name": "Gemini Alignment",
            "cmd": [python, _p("scripts", "07_gemini_alignment.py"), "--job-id", job_id]
        },
        {
            "id": 10, "name": "Onset DTW",
            "cmd": [python, _p("scripts", "08_onset_dtw.py"), "--job-id", job_id]
        },
        {
            "id": 11, "name": "Background Illustration",
            "cmd": [python, _p("scripts", "08b_background_image.py"), "--job-id", job_id]
        },
        {
            "id": 12, "name": "Video Rendering",
            "cmd": [python, _p("scripts", "09_video_rendering.py"), "--job-id", job_id]
        },
        {
            "id": 13, "name": "System Cleanup",
            "cmd": [python, _p("scripts", "11_system_cleanup.py"), "--job-id", job_id]
        },
        {
            "id": 14, "name": "Process Conclusion",
            "cmd": [python, _p("scripts", "13_process_conclusion.py"), "--job-id", job_id]
        }
    ])
    
    return steps

def main():
    parser = argparse.ArgumentParser(description="Modern Karaoke Pipeline Runner (CLI)")
    parser.add_argument("--audio", help="Path to input audio (MP3/WAV)")
    parser.add_argument("--lyrics", help="Path to input lyrics (TXT)")
    parser.add_argument("--lang", default="pt", help="Language tag (default: pt)")
    parser.add_argument("--romanization", default="none", choices=["none", "romaji", "pinyin"], help="Romanization mode")
    parser.add_argument("--job-id", help="Existing Job ID to resume, or specific ID to use")
    parser.add_argument("--resume", action="store_true", help="Resume from last failed step")
    parser.add_argument("--start-at", type=int, help="Force start at specific step ID")
    parser.add_argument("--aligner", default="mfa", choices=["mfa", "sofa"], help="Alignment engine (default: mfa)")
    
    args = parser.parse_args()
    
    # 1. Initialize Job ID
    if args.job_id:
        job_id = args.job_id
    else:
        # If no job-id provided and no audio/lyrics, we can't do much
        if not (args.audio and args.lyrics):
            print("ERRO: Forneça --audio e --lyrics para um novo job, ou --job-id para resumar.")
            sys.exit(1)
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        
    print(f"\n🚀 Pipeline Starting - Job ID: {job_id}")
    
    # 2. Setup Job Directory
    job_dir = kpaths.job_root(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if job exists in state
    job_data = state_store.get_job(job_id)
    
    if not job_data:
        # Initialize new job in state
        if not (args.audio and args.lyrics):
             print(f"ERRO: Job {job_id} não encontrado no estado. Forneça --audio e --lyrics.")
             sys.exit(1)
             
        input_dir = kpaths.input_dir(job_id)
        input_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy(args.audio, input_dir / "song.mp3")
        shutil.copy(args.lyrics, kpaths.lyrics_path(job_id))
        
        job_data = state_store.upsert_job(
            job_id, 
            audio_name=Path(args.audio).name,
            audio_hash="manual_run",
            lyrics_hash="manual_run",
            config_hash="manual_run",
            lang=args.lang,
            tool_versions={}
        )
        # Store romanization in a custom field if needed, but for now we just use args
        
    lang = job_data.get("lang", args.lang)
    romanization = args.romanization # We don't track romanization in state_store usually
    
    steps = build_steps(job_id, lang, romanization, args.aligner)
    
    # 3. Resume logic
    steps_to_skip = []
    if args.resume:
        steps_to_skip = resume_planner.get_resume_plan(job_data, steps)
        print(f"🔄 Resuming... Skipping {len(steps_to_skip)} completed steps.")
        
    start_index = 0
    if args.start_at:
        start_index = args.start_at - 1
        print(f"⏭️  Forcing start at Step {args.start_at}")
        
    # 4. Execution Loop
    for i in range(start_index, len(steps)):
        step = steps[i]
        step_id = step["id"]
        step_name = step["name"]
        cmd = step["cmd"]
        
        if "condition" in step and not step["condition"]:
            print(f"⏩ [STEP {step_id}/{len(steps)}] {step_name} - SKIPPED (Condição não atendida)")
            continue

        if step_name in steps_to_skip and not args.start_at:
            print(f"⏩ [STEP {step_id}/{len(steps)}] {step_name} - SKIPPED (Already completed)")
            continue
            
        print(f"\n--- [STEP {step_id}/{len(steps)}] {step_name} ---")
        
        rc = run_command(cmd)
        
        if rc == 0:
            print(f"\n✅ Step {step_id} completed successfully.")
            # We don't know the outputs here easily without scanning, but 
            # state_store.update_step usually tracks them. 
            # Scripts like 03_forced_align.py are supposed to update the state themselves!
            # If they don't, we can do a minimal update here to mark it "ok"
            state_store.update_step(job_id, step_name, "ok")
        else:
            print(f"\n❌ Step {step_id} failed with return code {rc}.")
            print(f"To resume later, use: python run_pipeline.py --job-id {job_id} --resume")
            sys.exit(1)
            
    print(f"\n✨ PIPELINE FINISHED SUCCESSFULLY for Job: {job_id} ✨")
    print(f"Outputs are located in: {job_dir}")

if __name__ == "__main__":
    main()
