# ADR-002 — MVP orientado à letra (lyrics-first)

**Status:** Aceito

## Contexto
Whisper (STT) diverge da letra real: erra palavras, omite repetições, inventa
texto. Karaokê exige o texto **exato** que foi cantado.

## Decisão
No MVP a **letra é obrigatória**. O caminho feliz usa **alinhamento forçado**
(`s03b_lyrics_align.py`) com a letra como *ground truth*. Whisper
(`s03_transcribe.py`) é apenas fallback técnico quando não há `lyrics.txt`.

## Consequências
- ✅ Texto correto garantido; alinhamento resolve só o *quando*, não o *quê*.
- ✅ `transcript.json` do caminho forçado carrega `alignment_mode="forced"` + rótulos de seção.
- ⚠️ Sem letra, cai-se no fallback menos confiável (ainda tratado como rascunho — ver Constituição §3).

Ver [../PRD.md](../PRD.md) e [../SDD.md](../SDD.md) §2.
