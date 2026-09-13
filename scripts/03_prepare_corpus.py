"""
03_prepare_corpus.py — Prepara o corpus textual para alinhamento CTC.

Normaliza a letra:
  - Expande contrações (I'm → I am)
  - Remove pontuação
  - Lowercase
  - Colapsa linhas em branco

Inputs  (via --job-id):
  input/jobs/{job_id}/lyrics.txt

Outputs (via --job-id):
  work/jobs/{job_id}/04_mfa_corpus/song.lab
"""
import re
import sys
import argparse
import shutil
from pathlib import Path

# Enforce UTF-8 for I/O in Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke.lyrics_cleaner import clean_lyrics_strict
import karaoke.paths as kpaths

def _progress(pct: int, msg: str = ""):
    """Emite linha de progresso parseável pelo server.py."""
    if msg:
        print(f"PROGRESS: {pct} | {msg}", flush=True)
    else:
        print(f"PROGRESS: {pct}", flush=True)

# ── Contraction expansion map ─────────────────────────────────────────────────
CONTRACTIONS = {
    "i'm":      "i am",
    "i'll":     "i will",
    "i'd":      "i would",
    "i've":     "i have",
    "it's":     "it is",
    "he's":     "he is",
    "she's":    "she is",
    "that's":   "that is",
    "what's":   "what is",
    "there's":  "there is",
    "here's":   "here is",
    "who's":    "who is",
    "let's":    "let us",
    "we're":    "we are",
    "they're":  "they are",
    "you're":   "you are",
    "we've":    "we have",
    "they've":  "they have",
    "you've":   "you have",
    "we'll":    "we will",
    "they'll":  "they will",
    "you'll":   "you will",
    "he'll":    "he will",
    "she'll":   "she will",
    "it'll":    "it will",
    "we'd":     "we would",
    "they'd":   "they would",
    "you'd":    "you would",
    "he'd":     "he would",
    "she'd":    "she would",
    "isn't":    "is not",
    "aren't":   "are not",
    "wasn't":   "was not",
    "weren't":  "were not",
    "don't":    "do not",
    "doesn't":  "does not",
    "didn't":   "did not",
    "won't":    "will not",
    "wouldn't": "would not",
    "can't":    "can not",
    "couldn't": "could not",
    "shouldn't":"should not",
    "hasn't":   "has not",
    "haven't":  "have not",
    "hadn't":   "had not",
    "'cause":   "cause",
    "ain't":    "am not",
}


def normalise_lyrics(raw: str) -> str:
    """Normaliza letra para alinhamento CTC — só texto limpo, sem pontuação."""
    text = raw.lower()

    # Normaliza aspas curvas para retas antes de expandir contrações
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    for contraction, expansion in CONTRACTIONS.items():
        text = text.replace(contraction, expansion)

    # Remove possessivos (falcon's → falcons)
    text = re.sub(r"(\w)'s\b", r"\1s", text)
    # Remove apóstrofos restantes
    text = text.replace("'", "")

    # Remove pontuação (preserva hífens dentro de palavras)
    text = re.sub(r"[^\w\s-]", " ", text)
    # Remove hífens isolados
    text = re.sub(r"(?<!\w)-|-(?!\w)", " ", text)

    # Colapsa espaços por linha, remove linhas vazias
    lines = [" ".join(line.split()) for line in text.splitlines()]
    result = "\n".join(line for line in lines if line)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True, help="Job ID para paths corretos")
    args = parser.parse_args()
    job_id = args.job_id

    print("=== Fase D: Preparar Corpus Textual ===")
    _progress(0, "Lendo arquivos de entrada...")

    # ── Paths baseados em job_id ──────────────────────────────────────────────
    lyrics_file = kpaths.lyrics_path(job_id)
    corpus_dir  = kpaths.corpus_dir(job_id)
    vocals_raw  = kpaths.vocals_raw(job_id)

    # ── Validações ────────────────────────────────────────────────────────────
    if not lyrics_file.exists():
        print(f"ERRO: Arquivo de letra não encontrado: {lyrics_file}")
        sys.exit(1)

    if not vocals_raw.exists():
        print(f"ERRO: Arquivo de vocal não encontrado: {vocals_raw}")
        print(f"  Esperado em: {vocals_raw}")
        sys.exit(1)

    # ── Lê e normaliza letra ──────────────────────────────────────────────────
    raw_lyrics = lyrics_file.read_text(encoding="utf-8")

    _progress(20, "Limpando e normalizando letra...")
    # ── Extração de Adlib Hints (Suno style) ──────────────────────────────────
    from karaoke.lyrics_cleaner import clean_lyrics_with_adlibs
    
    # Captura parênteses para o Gemini (Step 03c)
    _parse_result = clean_lyrics_with_adlibs(raw_lyrics)
    cleaned_with_hints, adlib_hints = _parse_result.lyrics, _parse_result.adlib_hints
    
    # Salva hints no diretório de alinhamento para o Gemini consumir depois
    align_dir = kpaths.alignment_dir(job_id)
    align_dir.mkdir(parents=True, exist_ok=True)
    hints_path = align_dir / "adlib_hints.json"
    
    import json
    with open(hints_path, "w", encoding="utf-8") as f:
        json.dump(adlib_hints, f, indent=2, ensure_ascii=False)
    print(f"  {len(adlib_hints)} adlib hints salvos em: {hints_path.name}")

    # ── MFA Corpus (song.lab) ────────────────────────────────────────────────
    # Primeiro passa pelo limpador de formato (remove tags Suno, etc)
    cleaned = clean_lyrics_strict(raw_lyrics)
    # Depois normaliza para alinhamento
    normalised = normalise_lyrics(cleaned)

    if not normalised.strip():
        print("ERRO: Letra ficou vazia após normalização. Verifique o conteúdo enviado.")
        sys.exit(1)

    word_count = len(normalised.split())
    print(f"  Letra normalizada: {word_count} palavras")

    # ── Prepara corpus ────────────────────────────────────────────────────────
    _progress(60, "Configurando diretório do corpus...")
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    lab_path = corpus_dir / "song.lab"
    lab_path.write_text(normalised.strip() + "\n", encoding="utf-8")
    print(f"  Corpus salvo: {lab_path}")

    # Copia vocals_raw para o corpus (para scripts que esperam song.wav aqui)
    target_wav = corpus_dir / "song.wav"
    _progress(80, "Copiando áudio para MFA...")
    shutil.copy(vocals_raw, target_wav)
    print(f"  Áudio copiado: {target_wav}")

    _progress(100, f"Corpus OK")
    print(f"✓ Corpus MFA preparado em {corpus_dir}")


if __name__ == "__main__":
    main()
