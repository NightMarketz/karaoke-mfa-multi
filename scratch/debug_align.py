
import sys
import torch
from pathlib import Path

# Add scripts to path for any dependencies if needed
sys.path.append(str(Path.cwd() / "scripts"))

try:
    from ctc_forced_aligner import (
        load_alignment_model,
        generate_emissions,
        preprocess_text,
        get_alignments,
        get_spans,
        postprocess_results,
        load_audio
    )
    print("Imports OK")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

# Sample lyrics from struggle_test
full_text = "Hmmmmm Hmmmmm Still Breathing"
language = "eng"
audio_file = "jobs/struggle_test/vocals.wav"

try:
    alignment_model, alignment_tokenizer = load_alignment_model(device="cpu", dtype=torch.float32)
    audio_waveform = load_audio(audio_file, alignment_model.dtype, alignment_model.device)
    emissions, stride = generate_emissions(alignment_model, audio_waveform, batch_size=1)
    
    tokens_starred, text_starred = preprocess_text(full_text, romanize=True, language=language)
    segments_raw, scores, blank_token = get_alignments(emissions, tokens_starred, alignment_tokenizer)
    spans = get_spans(tokens_starred, segments_raw, blank_token)
    word_results = postprocess_results(text_starred, spans, stride, scores)
    
    print("Alignment OK")
    if word_results:
        print(f"Sample word result: {word_results[0]}")
    else:
        print("No word results returned")
        
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
