import os
import hashlib
import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

def get_file_hash(path: str) -> str:
    """Calculates SHA-256 hash of a file."""
    if not os.path.exists(path):
        return ""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def get_text_hash(text: str) -> str:
    """Calculates SHA-256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def calculate_job_id(audio_path: str, lyrics_text: str, lang: str, config: Dict[str, Any]) -> str:
    """
    Computes a deterministic job ID based on core inputs.

    Preview-mode fields (preview_mode, preview_duration) are intentionally
    excluded so that a preview job and its promoted full job share the same
    job_id — enabling the promote workflow to reuse cached stems.
    """
    audio_hash = get_file_hash(audio_path)
    lyrics_hash = get_text_hash(lyrics_text.strip())

    # Strip preview-only keys before hashing so preview and full jobs are identical
    stable_config = {k: v for k, v in config.items()
                     if k not in ("preview_mode", "preview_duration", "preview_start")}
    config_json = json.dumps(stable_config, sort_keys=True)
    config_hash = get_text_hash(config_json)

    combined = f"{audio_hash}:{lyrics_hash}:{lang}:{config_hash}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()

def validate_step_outputs(outputs: Dict[str, str]) -> bool:
    """Checks if all output files listed for a step exist on disk."""
    if not outputs:
        return True # Some steps might not have disk outputs or we didn't track them
    
    for label, path in outputs.items():
        if not os.path.exists(path):
            logger.info(f"Output file missing: {label} -> {path}")
            return False
    return True

def get_resume_plan(job_data: Optional[Dict[str, Any]], current_steps: List[Dict[str, Any]]) -> List[str]:
    """
    Determines which steps can be skipped based on prior run state.
    Returns a list of step names to SKIP.

    Strategy: skip a step only when BOTH conditions hold:
      1. The step was recorded as "ok" in state.json
      2. All its declared output files still exist on disk

    A step whose outputs are missing is NOT skipped even if recorded ok.
    Steps after a gap are still evaluated independently — a manually
    replaced output file in a later step is respected rather than ignored.

    This differs from the old "break on first missing" behaviour which
    would force-rerun every step after the first cache miss, making it
    impossible to resume from a manually fixed intermediate result.
    """
    if not job_data:
        return []

    steps_to_skip = []
    recorded_steps = job_data.get("steps", {})

    for step in current_steps:
        step_name    = step["name"]
        recorded     = recorded_steps.get(step_name)

        if recorded and recorded.get("status") == "ok":
            if validate_step_outputs(recorded.get("outputs", {})):
                steps_to_skip.append(step_name)
            else:
                logger.info(f"[resume] Step '{step_name}' was ok but outputs missing — will re-run")
                # Do NOT break: later steps with intact outputs can still be skipped
        else:
            logger.info(f"[resume] Step '{step_name}' not ok — will re-run")

    return steps_to_skip