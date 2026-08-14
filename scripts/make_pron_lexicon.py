"""Generate a word->ARPAbet pronunciation lexicon for Stage 04 (HubertFA).

The HubertFA checkpoint only carries the 42 ``en/`` phones (plus ja/zh); it has
no Portuguese phone set, and s04 phonemises with ``g2p_en``, which mangles
non-English spelling. s04 lets any word bypass g2p_en via a lexicon file
(``models/hubertfa/<lang>_pron_dict.txt``), so the fix is to write that file
with the nearest en/ ARPAbet phones.

What has to be right is the VOWEL COUNT per word: s05 derives the syllable split
from it. Sound fidelity is secondary — the model only needs a plausible target.

Usage:
    python scripts/make_pron_lexicon.py \
        --lyrics jobs/<id>/lyrics.txt \
        --out models/hubertfa/pt_pron_dict.txt

    python scripts/make_pron_lexicon.py --demo   # self-check, no espeak needed

Requires espeak-ng installed (winget install eSpeak-NG.eSpeak-NG) plus the
``phonemizer`` package. Point PHONEMIZER_ESPEAK_LIBRARY at libespeak-ng.dll if
it is not in the default location.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_ESPEAK_DLL = r"C:\Program Files\eSpeak NG\libespeak-ng.dll"

_nfd = lambda s: unicodedata.normalize("NFD", s)

# ── IPA (espeak pt-br) → ARPAbet ───────────────────────────────────────────
DIGRAPHS = {"tʃ": ["CH"], "dʒ": ["JH"], "lj": ["L", "Y"], "nj": ["N", "Y"]}
VOWELS = {
    "a": "AA", "ɐ": "AH", "ɐ̃": "AH", "æ": "AH", "ə": "AH",
    "e": "EY", "ẽ": "EY", "ɛ": "EH",
    "i": "IY", "ĩ": "IY", "ɪ": "IH", "y": "IY",
    "o": "OW", "õ": "OW", "ɔ": "AO",
    "u": "UW", "ũ": "UW", "ʊ": "UH", "ʊ̃": "UH",
}
CONSONANTS = {
    "b": "B", "d": "D", "f": "F", "ɡ": "G", "g": "G", "k": "K", "l": "L",
    "m": "M", "n": "N", "ɲ": "NY", "p": "P", "r": "R", "ɾ": "R", "s": "S",
    "ʃ": "SH", "t": "T", "v": "V", "x": "HH", "z": "Z", "ʒ": "ZH",
    "ŋ": "NG", "j": "Y", "w": "W",
}
# A vowel right after another vowel is a glide: merged into one ARPAbet
# diphthong so the syllable count stays right.
GLIDES = {"ʊ", "ɪ", "j", "w", "y", "i", "ʊ̃"}
DIPHTHONGS = {
    ("AA", "UH"): "AW", ("AA", "IH"): "AY", ("AA", "IY"): "AY",
    ("EY", "IH"): "EY", ("EY", "IY"): "EY", ("EH", "IH"): "EY",
    ("OW", "IH"): "OY", ("OW", "IY"): "OY", ("AO", "IH"): "OY",
    ("OW", "UH"): "OW", ("AH", "UH"): "AW", ("AH", "IH"): "AY",
    ("AH", "IY"): "AY", ("IY", "UH"): "UW", ("EH", "UH"): "EH",
}
ARPA_VOWELS = {"AA", "AE", "AH", "AO", "AW", "AX", "AY", "EH", "ER",
               "EY", "IH", "IY", "OW", "OY", "UH", "UW"}

# espeak pt-br inserts an epenthetic schwa after a syllable-final /r/
# ("acorda" -> a-kɔ-ɾə-da), which invents a syllable. Dropped.
_R = {"r", "ɾ"}
# Words espeak reads as a letter NAME instead of a word ("é" -> "e agudo").
OVERRIDES = {"é": ["EH"], "e": ["IY"], "a": ["AA"], "o": ["OW"], "à": ["AA"]}

DIGRAPHS = {_nfd(k): v for k, v in DIGRAPHS.items()}
VOWELS = {_nfd(k): v for k, v in VOWELS.items()}
CONSONANTS = {_nfd(k): v for k, v in CONSONANTS.items()}
GLIDES = {_nfd(g) for g in GLIDES}


def units(ipa: str) -> list[tuple[str, bool]]:
    """Split IPA into (base+combining char, carries_stress) units."""
    ipa = _nfd(ipa).replace("ː", "").strip()
    out: list[tuple[str, bool]] = []
    i, stressed = 0, False
    while i < len(ipa):
        ch = ipa[i]
        if ch in "ˈˌ":
            stressed = True
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        j = i + 1
        while j < len(ipa) and unicodedata.combining(ipa[j]):
            j += 1
        out.append((ipa[i:j], stressed))
        stressed = False
        i = j
    return out


def to_arpabet(ipa: str, word: str = "") -> list[str]:
    """Map one word's IPA to ARPAbet phones from the model's en/ inventory."""
    if word.lower() in OVERRIDES:
        return list(OVERRIDES[word.lower()])
    pairs = units(ipa)
    us = [u for u, _ in pairs]
    phones: list[str] = []
    i = 0
    while i < len(us):
        pair = us[i] + (us[i + 1] if i + 1 < len(us) else "")
        if pair in DIGRAPHS:
            phones.extend(DIGRAPHS[pair])
            i += 2
            continue
        u, is_stressed = pairs[i]
        if u == "ə" and i > 0 and us[i - 1] in _R:
            i += 1                      # espeak's epenthetic schwa
            continue
        if u in VOWELS:
            arp = VOWELS[u]
            # A stressed vowel is a nucleus, never a glide ("prejuízo" = hiato).
            if phones and phones[-1] in ARPA_VOWELS and u in GLIDES and not is_stressed:
                merged = DIPHTHONGS.get((phones[-1], arp))
                if merged:
                    phones[-1] = merged
                else:   # no English diphthong for it — keep it as a glide
                    phones.append("W" if u in {_nfd("ʊ"), _nfd("ʊ̃"), "w", "u"} else "Y")
                i += 1
                continue
            phones.append(arp)
        elif u in CONSONANTS:
            phones.extend(["N", "Y"] if u == "ɲ" else [CONSONANTS[u]])
        else:
            raise AssertionError(f"IPA outside the map: {u!r} in {word!r} ({ipa!r})")
        i += 1
    return phones


# ── Independent syllable count, from spelling (control) ────────────────────
_ORTH_V = "aeiouáàâãéêíóôõúü"
_RISING = {"ia", "ie", "io", "iu", "ua", "ue", "ui", "uo",
           "ai", "ei", "oi", "au", "eu", "ou", "ão", "ãe", "õe"}


def orth_syllables(word: str) -> int:
    """Count spelling vowel groups, collapsing diphthongs. Approximate on
    purpose — it exists to disagree with the IPA count, not to be authoritative
    (it is wrong on hiatus and on English loanwords)."""
    groups = re.findall(f"[{_ORTH_V}]+", word.lower())
    n = 0
    for g in groups:
        i = 0
        while i < len(g):
            i += 2 if g[i:i + 2] in _RISING else 1
            n += 1
    return max(n, 1)


def unique_words(lyrics: Path) -> list[str]:
    """Unique singable words: [Section] markers and digits dropped."""
    words = []
    for line in lyrics.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or (line.startswith("[") and line.endswith("]")):
            continue
        words += [w.lower() for w in
                  re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", line, flags=re.UNICODE)]
    return sorted(set(words))


def model_inventory(vocab_path: Path, prefix: str = "en") -> set[str]:
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    return {k.split("/", 1)[1].upper()
            for k in vocab["vocab"] if k.startswith(f"{prefix}/")}


def demo() -> int:
    """Self-check on hand-written IPA — no espeak, no model needed."""
    # syllable count is the property that matters
    cases = {
        "arrasta":   ("ˌaxˈastæ", 3),
        "ilusão":    ("ˌiluzˈɐ̃ʊ̃", 3),
        "acorda":    ("ˌakˈɔɾədæ", 3),     # epenthetic schwa dropped
        "prejuízo":  ("prˌeʒuˈizʊ", 4),    # stressed i = hiatus, not a glide
        "bem":       ("bˈeɪŋ", 1),         # eɪ = one diphthong
        "é":         ("ˌɛaɡˈudʊ", 1),      # espeak spells the letter name out
    }
    for word, (ipa, want) in cases.items():
        phones = to_arpabet(ipa, word)
        got = sum(1 for p in phones if p in ARPA_VOWELS)
        assert got == want, f"{word}: {got} syllables, expected {want} ({phones})"
    # Negative control: the same schwa NOT preceded by /r/ must survive and
    # add a syllable — otherwise the rule above is passing for the wrong reason.
    assert sum(1 for p in to_arpabet("ˌakˈɔtədæ", "x")
               if p in ARPA_VOWELS) == 4, "schwa is being dropped everywhere"
    assert to_arpabet("ˈa", "a") == ["AA"]
    print("make_pron_lexicon demo OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lyrics", type=Path, help="lyrics.txt to build the lexicon from")
    ap.add_argument("--out", type=Path, help="output <lang>_pron_dict.txt")
    ap.add_argument("--language", default="pt-br", help="espeak voice (default: pt-br)")
    ap.add_argument("--vocab", type=Path, default=Path("models/hubertfa/vocab.json"),
                    help="HubertFA vocab.json, to check every phone exists")
    ap.add_argument("--espeak-lib", default=os.environ.get(
        "PHONEMIZER_ESPEAK_LIBRARY", DEFAULT_ESPEAK_DLL))
    ap.add_argument("--demo", action="store_true", help="run the self-check and exit")
    args = ap.parse_args()

    if args.demo:
        return demo()
    if not args.lyrics or not args.out:
        ap.error("--lyrics and --out are required (or use --demo)")

    os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = str(args.espeak_lib)
    try:
        from phonemizer.backend import EspeakBackend
    except ImportError:
        print("phonemizer is not installed: pip install phonemizer", file=sys.stderr)
        return 1

    words = unique_words(args.lyrics)
    if not words:
        print(f"No singable word found in {args.lyrics}", file=sys.stderr)
        return 1

    backend = EspeakBackend(args.language, with_stress=True,
                            language_switch="remove-flags")
    ipas = backend.phonemize(words, strip=True)
    assert len(ipas) == len(words), f"1:1 broken: {len(ipas)} != {len(words)}"

    inventory = model_inventory(args.vocab) if args.vocab.exists() else set()

    lines, divergences = [], []
    for word, ipa in zip(words, ipas):
        phones = to_arpabet(ipa, word)
        assert phones, f"empty phones for {word!r}"
        if inventory:
            outside = [p for p in phones if p not in inventory]
            assert not outside, f"outside the en/ inventory: {outside} in {word}"
        n_ipa = sum(1 for p in phones if p in ARPA_VOWELS)
        n_orth = orth_syllables(word)
        if n_ipa != n_orth:
            divergences.append((word, ipa, " ".join(phones), n_ipa, n_orth))
        lines.append(f"{word}\t{' '.join(phones)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        f"# {args.language} word -> ARPAbet (nearest en/ phones), from espeak-ng.\n"
        f"# Generated by scripts/make_pron_lexicon.py from {args.lyrics.name}.\n"
        "# What matters is the vowel count = syllable count (s05 splits on it).\n"
        + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(f"lexicon: {len(lines)}/{len(words)} words -> {args.out}")
    print(f"syllable divergence IPA vs spelling: {len(divergences)}/{len(words)} "
          f"(inspect these by hand — the spelling counter is the weaker of the two)")
    for word, ipa, arpa, n_ipa, n_orth in divergences:
        print(f"  {word:14s} ipa={ipa:22s} arpa={arpa:30s} ipa={n_ipa} spelling={n_orth}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
