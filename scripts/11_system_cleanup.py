"""
11_system_cleanup.py — Step 11: Limpeza e arquivamento de arquivos temporários.

Remove arquivos grandes de processamento intermediário (stems do Demucs)
e prepara o diretório de trabalho para arquivamento.
"""
import argparse
import shutil
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import karaoke.paths as kpaths

def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}", flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--keep-all", action="store_true", help="Não deletar nada")
    args = parser.parse_args()
    job_id = args.job_id

    print(f"=== Step 11: System Cleanup for {job_id} ===")
    _progress(0, "Iniciando limpeza do sistema...")

    sep_dir = kpaths.separation_dir(job_id)
    
    if args.keep_all:
        print("  Modo 'keep-all' ativado. Nenhuma remoção será feita.")
        _progress(100, "Cleanup pulado.")
        return

    # 1. Remove Demucs output (usually the largest files)
    _progress(30, "Removendo stems intermediários...")
    # htdemucs/{job_id} contains bass.wav, drums.wav, other.wav, etc.
    demucs_job_dir = kpaths.demucs_out_dir(job_id)
    
    files_to_remove = ["bass.wav", "drums.wav", "other.wav"]
    for f in files_to_remove:
        file_path = demucs_job_dir / f
        if file_path.exists():
            file_path.unlink()
            print(f"  - {f} removido.")

    # 2. Archiving (Optional logic could go here)
    # e.g., shutil.make_archive(...)

    _progress(100, "System Cleanup concluído.")

if __name__ == "__main__":
    main()
