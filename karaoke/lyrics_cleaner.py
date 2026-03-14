"""
lyrics_cleaner.py — Strip Suno AI / production annotations from raw lyrics.
Keeps only the words that are actually sung.
Pure function, no I/O.

Suno prompt syntax:
  [bracketed]      → stage/production directions, always removed
  (parenthesized)  → either adlib/backing vocal OR stage direction
  (adbl            → truncated adlib marker, always removed
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ── Regex ─────────────────────────────────────────────────────────────────────

RE_BRACKET_LINE   = re.compile(r'^\s*\[.*?\]\s*$')
RE_BRACKET_INLINE = re.compile(r'\[.*?\]')
RE_UNCLOSED_PAREN = re.compile(r'\([^)]{0,30}$')
RE_PAREN          = re.compile(r'\(([^)]*)\)')
RE_MULTI_EXCL     = re.compile(r'!{2,}')
RE_MULTI_DOTS     = re.compile(r'\.{4,}')
RE_WHITESPACE     = re.compile(r'\s{2,}')

# ── Stage direction keywords ───────────────────────────────────────────────────
# These signal that a parenthetical is a production note, NOT a sung adlib.
STAGE_KEYWORDS = {
    'adbl', 'whisper', 'scream', 'pause', 'silence', 'spoken',
    'instrumental', 'guitar', 'drums', 'bass', 'tempo', 'vocal',
    'sound', 'ambient', 'heavy', 'slow', 'building', 'rising',
    'cuts', 'music', 'chaotic', 'breakdown', 'feedback', 'drone',
    'staccato', 'melodic', 'soaring', 'epical', 'atmosphere',
    'maximum', 'volume', 'half-time', 'strain', 'adlibs',
    'repetitive', 'chant', 'riff', 'solo', 'interlude', 'explosion',
    'industrial', 'aggressive', 'monotone', 'melancholic', 'dissonant',
    'gritty', 'clean', 'move', 'path', 'choose', 'this is',
}

# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class LyricsParseResult:
    """
    Full parse result from clean_lyrics_with_adlibs().

    lyrics      : clean lyric text for MFA/WhisperX alignment
    adlib_hints : list of (line_number_in_lyrics, adlib_text) — approximate
                  position hints for adlibs detected from parentheticals.
                  Line numbers are 1-indexed within the cleaned lyrics output.
    """
    lyrics:      str
    adlib_hints: List[Tuple[int, str]] = field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_stage_direction(content: str) -> bool:
    """
    Returns True if a parenthetical is a production/stage note.
    Returns False if it looks like a sung adlib or backing vocal.
    """
    lower = content.lower().strip()
    if not lower:
        return True
    # Explicit stage keywords
    for kw in STAGE_KEYWORDS:
        if kw in lower:
            return True
    # Remove Suno-style tags [Verse], [Chorus], (Ooh), etc.
    lower = re.sub(r"\[.*?\]", "", lower)
    lower = re.sub(r"\(.*?\)", "", lower)
    # Contains stage-direction punctuation patterns like "... stop move..."
    if re.search(r'\.\.\.\s+\w+\s+\w+', lower):
        return True
    return False


def _normalize(line: str) -> str:
    line = RE_MULTI_EXCL.sub('!', line)
    line = RE_MULTI_DOTS.sub('...', line)
    line = RE_WHITESPACE.sub(' ', line)
    return line.strip()


# ── Public API ────────────────────────────────────────────────────────────────

def clean_lyrics_with_adlibs(raw: str) -> LyricsParseResult:
    """
    Full parse: returns clean lyrics AND adlib hints extracted from
    Suno-style (parenthesized) backing vocals.

    Use this when you want to pre-seed the adlib detector with known
    adlib positions from the prompt itself.
    """
    lines       = raw.split('\n')
    lyric_lines : List[str]          = []
    adlib_hints : List[Tuple[int, str]] = []

    for line in lines:
        # Skip lines that are entirely [bracketed]
        if RE_BRACKET_LINE.match(line):
            continue

        # Remove inline [brackets]
        line = RE_BRACKET_INLINE.sub('', line)

        # Remove truncated adlib markers like "(adbl"
        line = RE_UNCLOSED_PAREN.sub('', line)

        # Handle (parentheticals)
        collected_adlibs: List[str] = []

        def paren_handler(m: re.Match) -> str:
            content = m.group(1).strip()
            if not content:
                return ''
            if _is_stage_direction(content):
                return ''
            # It's a sung adlib/backing vocal → capture it, remove from main line
            collected_adlibs.append(content)
            return ''

        line = RE_PAREN.sub(paren_handler, line)
        line = _normalize(line)

        # Record adlib hints tied to approximate lyric line position
        # (line count BEFORE appending this line, so adlib appears "at" this line)
        current_lyric_line = len([l for l in lyric_lines if l]) + 1
        for adlib_text in collected_adlibs:
            adlib_hints.append((current_lyric_line, adlib_text))

        lyric_lines.append(line)

    # Collapse multiple blanks
    result_lines: List[str] = []
    prev_blank = False
    for line in lyric_lines:
        if not line:
            if not prev_blank:
                result_lines.append('')
            prev_blank = True
        else:
            result_lines.append(line)
            prev_blank = False

    lyrics = '\n'.join(result_lines).strip()
    return LyricsParseResult(lyrics=lyrics, adlib_hints=adlib_hints)


def clean_lyrics(raw: str) -> str:
    """
    Clean Suno lyrics to plain sung text.
    Adlibs in (parens) are silently dropped — use clean_lyrics_with_adlibs()
    if you need them.
    """
    return clean_lyrics_with_adlibs(raw).lyrics


def clean_lyrics_strict(raw: str) -> str:
    """
    Extra-strict: also removes lines that are just punctuation/ellipsis.
    Used by the web API endpoint /api/clean_lyrics.
    """
    text  = clean_lyrics(raw)
    lines = text.split('\n')
    out   = []
    for line in lines:
        stripped = line.strip()
        if stripped and all(c in '.!?…, ' for c in stripped):
            continue
        out.append(line)
    return '\n'.join(out).strip()


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    sample = """
[Intro]
[Long Instrumental Intro]
Still...
[Pre-Chorus]
Running on fumes... sealed in the tomb
[Chorus]
[Explosion]
'Cause I'm still here!
[Vocal Strain with adlibs]
Falcon's call...
Fuck it all!
I won't fall...
I must carry on!
[Outro Hook]
I won't fall... for that...
I must carry on!
I won't fall... (For that!)
I must carry on!
I won't fall... (Fuck that!)
[Bridge]
Oh, Fuck!!!!!
(Please, stop move...)
Cannot catch a breath...
(This is the path you choose...)
(adbl
"""
    result = clean_lyrics_with_adlibs(sample)
    print("=== LYRICS ===")
    print(result.lyrics)
    print("\n=== ADLIB HINTS ===")
    for line_no, text in result.adlib_hints:
        print(f"  Line ~{line_no}: '{text}'")
