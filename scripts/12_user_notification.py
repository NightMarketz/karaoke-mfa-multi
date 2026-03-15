"""
12_user_notification.py — Step 12: Notificação de conclusão do job.

Envia notificações via Webhook (Discord/Slack) ou printa resumo final.
"""
import argparse
import sys
import os
import json
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

    print(f"=== Step 12: User Notification for {job_id} ===")
    _progress(0, "Preparando notificação...")

    out_mp4 = kpaths.output_video(job_id)
    
    # Logic to send to Discord/Webhook if configured
    webhook_url = os.environ.get("KARAOKE_WEBHOOK_URL")
    
    msg = f"✅ **Karaoke Concluído!**\nJob: `{job_id}`\nArquivo: `{out_mp4.name}`"
    
    if webhook_url:
        print(f"  Enviando notificação para Webhook...")
        try:
            import requests # Must be installed
            requests.post(webhook_url, json={"content": msg})
        except Exception as e:
            print(f"  Aviso: falha ao enviar webhook: {e}")
    else:
        print("  Webhook não configurado. Notificação local apenas.")

    _progress(100, "Notification concluído.")
    print(f"MESSAGE: {msg}")

if __name__ == "__main__":
    main()
