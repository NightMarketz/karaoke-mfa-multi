"""
04_mfa_alignment.py — Step 04: Alinhamento Primário via Montreal Forced Aligner (MFA).

Consolida a preparação de corpus e a execução do alinhamento CTC.
"""
import argparse
import subprocess
import sys
import shutil
import json
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import karaoke.paths as kpaths

# lang -> nome do modelo/dicionario MFA instalado. Acoustic e dictionary usam o
# mesmo nome nos modelos oficiais do MFA (english_mfa, portuguese_mfa, ...).
MFA_MODELS = {"en": "english_mfa", "pt": "portuguese_mfa"}

# Beam alargado de proposito: os modelos acusticos do MFA sao treinados em FALA, e
# voz cantada estica vogais e desvia do timing esperado o suficiente para o beam
# default (10/40) nao fechar nenhum alinhamento — media NoAlignmentsError mesmo com
# OOV em 1.4%. 100/400 e o valor que a propria mensagem de erro do MFA sugere.
# Knob de calibracao: material com voz mais limpa aceita beam menor (mais rapido).
MFA_BEAM = 100
MFA_RETRY_BEAM = 400


def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}", flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--lang", default="pt",
                        help="Codigo de idioma; escolhe o modelo/dicionario MFA (ver MFA_MODELS)")
    args = parser.parse_args()
    job_id = args.job_id
    lang = args.lang

    print(f"=== Step 04: MFA Alignment for {job_id} ===")
    _progress(0, "Iniciando alinhamento MFA...")

    # 1. Corpus: usa o que 03_prepare_corpus.py ja preparou (song.wav + song.lab).
    # Este passo ANTES reimplementava o preparo lendo lyrics.txt cru e aplicando
    # .upper() — e os dicionarios oficiais do MFA sao inteiramente minusculos
    # (english_mfa: 0 de 42353 entradas em maiuscula), entao 100% das palavras
    # ficavam OOV e o align morria com NoAlignmentsError. O texto normalizado do
    # step 03 da 1.4% de OOV no mesmo material.
    corpus_dir = kpaths.mfa_corpus_dir(job_id)
    corpus_lab = corpus_dir / "song.lab"
    corpus_wav = corpus_dir / "song.wav"

    if not corpus_lab.exists() or not corpus_wav.exists():
        print(f"ERRO: corpus incompleto em {corpus_dir}. Rode 03_prepare_corpus.py primeiro.")
        print(f"  esperado: {corpus_lab.name} e {corpus_wav.name}")
        sys.exit(1)
        
    _progress(30, "Corpus preparado. Iniciando alinhamento...")

    # 2. Executar MFA
    out_tg = kpaths.mfa_textgrid(job_id)
    out_tg.parent.mkdir(parents=True, exist_ok=True)
    
    # Command structure using conda run.
    # Dicionario e modelo vao por NOME (o MFA resolve o que esta instalado via
    # `mfa model download`), nao por caminho de arquivo: o antigo
    # "input/dicts/pt_mfa.dict" nunca existiu no repo — input/ e gitignored.
    model_name = MFA_MODELS.get(lang, MFA_MODELS["pt"])
    dict_path = model_name
    
    cmd = [
        "conda", "run", "-n", "mfa_env",
        "mfa", "align",
        str(corpus_dir),
        dict_path,
        model_name,
        str(out_tg.parent),
        "--clean", "--overwrite",
        "--beam", str(MFA_BEAM),
        "--retry_beam", str(MFA_RETRY_BEAM),
    ]
    
    print(f"CMD: {' '.join(cmd)}")
    
    try:
        # MFA can be noisy, but we want to see if it fails
        subprocess.run(cmd, check=True)
        print("✓ MFA concluído.")
    except Exception as e:
        print(f"ERRO ao executar MFA: {e}")
        # Note: In a real pipeline, we might fall back to WhisperX if MFA fails here
        sys.exit(1)

    # Validate output
    # MFA usually outputs as {job_id}/vocals.TextGrid in the output folder
    # MFA nomeia o TextGrid pelo stem da utterance — agora song.lab, nao vocals.txt
    mfa_result = out_tg.parent / "song.TextGrid"
    if mfa_result.exists() and mfa_result != out_tg:
        shutil.move(mfa_result, out_tg)

    if not out_tg.exists():
        print(f"ERRO: Alinhamento falhou, TextGrid não encontrado em {out_tg}")
        sys.exit(1)

    _progress(100, "MFA Alignment concluído.")

if __name__ == "__main__":
    main()
