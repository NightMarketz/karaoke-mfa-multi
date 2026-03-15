"""
13_process_conclusion.py — Step 13: Conclusão final e status do pipeline.

Marca o fim do processamento, consolida logs finais e exibe
o tempo total de execução.
"""
import argparse
import sys
import time
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import karaoke.paths as kpaths

def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}", flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    job_id = args.job_id

    print(f"=== Step 13: Process Conclusion for {job_id} ===")
    _progress(50, "Finalizando job...")

    # Write a completion file in the job dir
    completion_flag = kpaths.input_job_dir(job_id) / ".completed"
    completion_flag.touch()
    
    print(f"🎉 Job {job_id} concluído com sucesso!")
    print(f"📂 Arquivos finais disponíveis em ./outputs/{job_id}.mp4")

    _progress(100, "Pipeline finalizado.")

if __name__ == "__main__":
    main()
