"""
test_lyrics_robustness.py — Comprehensive unit tests for section marker parsing.

Tests _parse_lyrics, _resolve_section, _is_stage_direction, _build_full_text,
_split_words_by_lines, and _snap_to_onsets.

Coverage areas:
    _resolve_section       — every SECTION_TO_STYLE entry, numeric strip,
                             every PREFIX_FALLBACK prefix, unknown fallback,
                             edge cases (empty, whitespace, unicode)
    _is_stage_direction    — true/false/boundary, property over full dict
    _parse_lyrics          — section assignment, persistence across blank lines,
                             consecutive markers, numbered markers, PT/ES/EDM,
                             mixed case, verbose directions skipped, unknown
                             tracking, multiple/repeated unknowns, inline
                             stripping, apostrophes, purely-inline lines,
                             punctuation-only lines, empty file, markers-only,
                             directions-only, unicode text, Suno patterns
    _build_full_text       — ordering, single line, empty, contractions
    _split_words_by_lines  — basic, timestamps, overflow, extra words,
                             probability mapping, section propagation
    _snap_to_onsets        — basic snap, outside window, empty list,
                             inversion guard, overlap guard, segment update,
                             zero-window disable
    Property tests         — _resolve_section never errors, always valid style;
                             _is_stage_direction always bool; _parse_lyrics
                             output always has alphabetic content
    Regression             — Struggle lyrics.txt end-to-end

Usage:
    python scripts/test_lyrics_robustness.py
    python scripts/test_lyrics_robustness.py -v   # verbose (shows PASSes too)
"""

from __future__ import annotations

import sys, tempfile, os, argparse, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from s03b_lyrics_align import (
    _parse_lyrics, _resolve_section, _is_stage_direction,
    _build_full_text, _split_words_by_lines, _snap_to_onsets,
    SECTION_TO_STYLE, _SECTION_PREFIX_FALLBACK,
)
from scripts.karaoke_styles.library import supported_style_keys

_G = "\033[32m"; _R = "\033[31m"; _X = "\033[0m"
_passed = _failed = 0
_verbose = False


def _ok(desc):
    global _passed; _passed += 1
    if _verbose: print(f"  {_G}PASS{_X}  {desc}")


def _fail(desc, detail=""):
    global _failed; _failed += 1
    print(f"  {_R}FAIL{_X}  {desc}")
    if detail: print(f"         {detail}")


def check(cond, desc, detail=""):
    _ok(desc) if cond else _fail(desc, detail)


def heading(title):
    print(f"\n{'-'*62}\n  {title}\n{'-'*62}")


def _lf(content):
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
    f.write(content); f.close(); return Path(f.name)


def _rm(p):
    try: os.unlink(p)
    except: pass


def _w(word, start, end, score=0.9):
    return {"word": word, "start": start, "end": end, "score": score}


def _seg(words):
    ww = [dict(w) for w in words]
    return {"text": " ".join(w["word"] for w in ww), "section": "verse",
            "start": ww[0]["start"], "end": ww[-1]["end"], "words": ww}


# -----------------------------------------------------------------
# _resolve_section
# -----------------------------------------------------------------

def test_resolve_exact_all_55_entries():
    heading(f"_resolve_section — every SECTION_TO_STYLE entry ({len(SECTION_TO_STYLE)} total)")
    for label, expected in SECTION_TO_STYLE.items():
        canonical, style = _resolve_section(label)
        check(style == expected, f"[{label}] -> {expected}", f"got '{style}'")
        check(canonical == label, f"[{label}] canonical preserved", f"got '{canonical}'")


def test_resolve_numeric_strip():
    heading("_resolve_section — numeric suffix strip")
    cases = [
        ("chorus 2","chorus"),("chorus 3","chorus"),("chorus 4","chorus"),("chorus 10","chorus"),
        ("verse 2","verse"),("verse 3","verse"),("verse 4","verse"),
        # These pinned s03b's internal map value, not what a listener
        # saw: s05 was already rendering a pre-chorus with the PreChorus
        # style. s03b now says so itself, so the two agree.
        ("pre-chorus 2","prechorus"),("pre-chorus 3","prechorus"),("pre-chorus 4","prechorus"),
        ("hook 2","chorus"),("hook 3","chorus"),("drop 3","chorus"),("drop 4","chorus"),
        ("bridge 2","bridge"),("verse (2)","verse"),("verse (3)","verse"),
        ("chorus (2)","chorus"),("outro (2)","outro"),
    ]
    for label, expected in cases:
        _, style = _resolve_section(label)
        check(style == expected, f"[{label}] -> {expected} (strip)", f"got '{style}'")


def test_resolve_all_prefix_fallbacks():
    heading("_resolve_section — every prefix in _SECTION_PREFIX_FALLBACK activates")
    for prefix, expected_style in _SECTION_PREFIX_FALLBACK.items():
        test_label = prefix + " xyztest"
        if test_label in SECTION_TO_STYLE:
            continue
        _, style = _resolve_section(test_label)
        check(style == expected_style,
              f"prefix '{prefix}' -> {expected_style} via [{test_label}]",
              f"got '{style}'")


def test_resolve_unknown_defaults_verse():
    heading("_resolve_section — unknown labels -> verse")
    for label in ["xyz","aaabbb","random words here","12345","totally unknown xyz",
                  "foobar section","new genre label","custom marker","section a"]:
        _, style = _resolve_section(label)
        check(style == "verse", f"[{label}] -> verse (unknown)", f"got '{style}'")


def test_resolve_edge_cases():
    heading("_resolve_section — edge: empty/whitespace/punctuation never crash")
    for label in ["", " ", "  ", "---", "...", "!!!"]:
        try:
            _, style = _resolve_section(label)
            check(style == "verse", f"['{label}'] -> verse (edge)", f"got '{style}'")
        except Exception as e:
            _fail(f"['{label}'] raised: {e}")


def test_resolve_all_keys_are_lowercase():
    heading("_resolve_section — all SECTION_TO_STYLE keys are lowercase")
    for key in SECTION_TO_STYLE:
        check(key == key.lower(), f"'{key}' is lowercase", "mixed-case key found")


def test_resolve_unicode():
    heading("_resolve_section — unicode accented labels")
    for label, expected in [("refrão","chorus"),("refrán","chorus"),
                             ("estrofe","verse"),("estrofa","verse"),("ponte","bridge")]:
        _, style = _resolve_section(label)
        check(style == expected, f"[{label}] -> {expected}", f"got '{style}'")


# -----------------------------------------------------------------
# _is_stage_direction
# -----------------------------------------------------------------

def test_stage_known_sections_never_direction():
    heading("_is_stage_direction — PROPERTY: every SECTION_TO_STYLE key -> False")
    for label in SECTION_TO_STYLE:
        result = _is_stage_direction(label)
        check(not result, f"'{label}' -> False (known section guard)", f"got True")


def test_stage_word_count_threshold():
    heading("_is_stage_direction — >4 words always True, <=4 words without keyword -> False")
    for label in ["new section here","some part one","part a","section x","random stage direction"]:
        if label in SECTION_TO_STYLE: continue
        check(not _is_stage_direction(label),
              f"'{label}' ({len(label.split())} words, no keyword) -> False")

    for label in ["this is definitely a stage direction","a b c d e",
                  "some totally unknown very long label"]:
        check(_is_stage_direction(label),
              f"'{label}' ({len(label.split())} words) -> True (>4 words)")


def test_stage_keywords_trigger():
    heading("_is_stage_direction — keyword-triggered (<=4 words)")
    for label in ["drums intro","snare fill","kick pattern","ambient pad",
                  "distortion riff","feedback loop","noise floor",
                  "tension peak","scream part","whisper here","backing track"]:
        if label in SECTION_TO_STYLE: continue
        check(_is_stage_direction(label), f"'{label}' -> True (keyword)", f"got False")


def test_stage_false_negatives_avoided():
    heading("_is_stage_direction — common section labels must be False")
    for label in ["guitar solo","spoken word","spoken","instrumental","solo",
                  "break","build","dialogue","transition"]:
        check(not _is_stage_direction(label),
              f"'{label}' -> False (must not be direction)", f"got True")


def test_stage_exactly_four_words():
    heading("_is_stage_direction — exactly 4 words boundary cases")
    # 4 words, no keyword -> False
    for label in ["some part one a","this is my thing","part alpha beta gamma"]:
        if label in SECTION_TO_STYLE: continue
        check(not _is_stage_direction(label),
              f"'{label}' (4 words, no keyword) -> False")
    # 4 words + keyword -> True
    for label in ["heavy drums kick hard","loud scream part here"]:
        check(_is_stage_direction(label),
              f"'{label}' (4 words + keyword) -> True")


def test_stage_property_always_bool():
    heading("_is_stage_direction — PROPERTY: never raises, always returns bool")
    for label in (list(SECTION_TO_STYLE.keys()) +
                  ["xyz","","  ","a b c d e f g","drums kick in","refrão","12345","!!!"]):
        try:
            result = _is_stage_direction(label)
            check(isinstance(result, bool), f"'{label[:30]}' -> bool",
                  f"got {type(result).__name__}")
        except Exception as e:
            _fail(f"'{label[:30]}' raised: {e}")


# -----------------------------------------------------------------
# _parse_lyrics — section assignment
# -----------------------------------------------------------------

def test_parse_basic():
    heading("_parse_lyrics — basic section assignment")
    lf = _lf("[Intro]\nStill\n\n[Verse]\nBreathing\nRunning\n\n[Chorus]\nCause Im here\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 4, f"4 lines (got {len(lines)})")
        for expected, i in [("intro",0),("verse",1),("verse",2),("chorus",3)]:
            check(lines[i]['section'] == expected,
                  f"line {i} -> {expected}", f"got '{lines[i]['section']}'")
    finally: _rm(lf)


def test_parse_section_persists_multi_line():
    heading("_parse_lyrics — section persists across multiple lines")
    lf = _lf("[Chorus]\nLine one\nLine two\nLine three\n[Verse]\nLine four\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 4, f"4 lines (got {len(lines)})")
        for i in range(3):
            check(lines[i]['section'] == 'chorus', f"line {i} -> chorus (persistence)")
        check(lines[3]['section'] == 'verse', "line 3 -> verse after new marker")
    finally: _rm(lf)


def test_parse_section_persists_across_blanks():
    heading("_parse_lyrics — section persists across blank lines")
    lf = _lf("[Chorus]\nLine one\n\n\nLine two\n\n\n\nLine three\n")
    try:
        lines = _parse_lyrics(lf)
        check(all(l['section'] == 'chorus' for l in lines),
              f"All lines under chorus", f"got {[l['section'] for l in lines]}")
    finally: _rm(lf)


def test_parse_no_markers_defaults_verse():
    heading("_parse_lyrics — no markers -> all verse")
    lf = _lf("Line one\nLine two\nLine three\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 3, f"3 lines")
        for line in lines:
            check(line['section'] == 'verse', f"'{line['text']}' -> verse")
    finally: _rm(lf)


def test_parse_numbered_markers():
    heading("_parse_lyrics — numbered markers resolve correctly")
    lf = _lf("[Chorus 3]\nC3 line\n[Verse 2]\nV2 line\n[Pre-Chorus 2]\nPC2 line\n")
    try:
        lines = _parse_lyrics(lf)
        styles = [_resolve_section(l['section'])[1] for l in lines]
        check(styles[0] == 'chorus', f"Chorus 3 -> chorus (got {styles[0]})")
        check(styles[1] == 'verse',  f"Verse 2 -> verse (got {styles[1]})")
        check(styles[2] == 'prechorus', f"Pre-Chorus 2 -> prechorus (got {styles[2]})")
    finally: _rm(lf)


def test_parse_pt_es_edm_markers():
    heading("_parse_lyrics — PT/ES/EDM markers")
    lf = _lf("[refrão]\nL1\n[Ponte]\nL2\n[Hook 2]\nL3\n[Drop 2]\nL4\n[estrofe]\nL5\n")
    try:
        lines = _parse_lyrics(lf)
        styles = [_resolve_section(l['section'])[1] for l in lines]
        expected = ['chorus','bridge','chorus','chorus','verse']
        for i, (got, exp) in enumerate(zip(styles, expected)):
            check(got == exp, f"line {i} -> {exp} (got {got})")
    finally: _rm(lf)


def test_parse_mixed_case_markers():
    heading("_parse_lyrics — mixed-case markers lowercased")
    lf = _lf("[CHORUS]\nL1\n[Verse]\nL2\n[BRIDGE]\nL3\n[Outro Chorus]\nL4\n")
    try:
        lines = _parse_lyrics(lf)
        styles = [_resolve_section(l['section'])[1] for l in lines]
        for exp, got, label in [
            ('chorus',styles[0],'CHORUS'),('verse',styles[1],'Verse'),
            ('bridge',styles[2],'BRIDGE'),('outro',styles[3],'Outro Chorus'),
        ]:
            check(got == exp, f"[{label}] -> {exp} (got {got})")
    finally: _rm(lf)


def test_parse_consecutive_markers_no_text():
    heading("_parse_lyrics — consecutive markers without text")
    lf = _lf("[Intro]\n[Verse]\nLine one\n[Bridge]\n[Chorus]\nLine two\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 2, f"2 lines (got {len(lines)})")
        check(lines[0]['section'] == 'verse',  f"line 0 -> verse after [Intro][Verse]")
        check(lines[1]['section'] == 'chorus', f"line 1 -> chorus after [Bridge][Chorus]")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _parse_lyrics — stage directions
# -----------------------------------------------------------------

def test_parse_verbose_directions_skipped():
    heading("_parse_lyrics — verbose stage directions skipped silently")
    lf = _lf("[Verse]\nLine one\n[Heavy Wall of Sound Loud Drums]\n[Chorus]\nLine two\n[Slow building tension riff starts]\nLine three\n")
    try:
        lines = _parse_lyrics(lf)
        texts = [l['text'] for l in lines]
        sections = [l['section'] for l in lines]
        check(texts[0] == 'Line one', "Line one preserved")
        check(sections[0] == 'verse',  "Line one -> verse")
        check(texts[1] == 'Line two',  "Line two preserved")
        check(sections[1] == 'chorus', "Line two -> chorus (direction didn't change section)")
        check(sections[2] == 'chorus', "Line three -> chorus (direction didn't change section)")
        all_unk = set(m for l in lines for m in l.get('unknown_markers', []))
        check('Heavy Wall of Sound Loud Drums' not in all_unk,
              "Verbose direction NOT in unknown_markers")
    finally: _rm(lf)


def test_parse_direction_doesnt_corrupt_section():
    heading("_parse_lyrics — direction between verses doesn't corrupt section")
    lf = _lf("[Verse]\nLine one\n[Drums kick in with heavy energy]\n[Verse]\nLine two\n")
    try:
        lines = _parse_lyrics(lf)
        check(all(l['section'] == 'verse' for l in lines),
              "Both lines under verse", f"{[l['section'] for l in lines]}")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _parse_lyrics — unknown markers
# -----------------------------------------------------------------

def test_parse_unknown_tracked():
    heading("_parse_lyrics — unknown markers tracked")
    lf = _lf("[Verse]\nLine one\n[Totally Unknown XYZ]\nLine two\n")
    try:
        lines = _parse_lyrics(lf)
        all_unk = sorted(set(m for l in lines for m in l.get('unknown_markers', [])))
        check('Totally Unknown XYZ' in all_unk,
              "'Totally Unknown XYZ' tracked", f"got {all_unk}")
    finally: _rm(lf)


def test_parse_multiple_unknowns_accumulated():
    heading("_parse_lyrics — multiple unknowns accumulate")
    lf = _lf("[Verse]\nL1\n[Unknown Alpha]\nL2\n[Chorus]\nL3\n[Unknown Beta]\nL4\n")
    try:
        lines = _parse_lyrics(lf)
        all_unk = sorted(set(m for l in lines for m in l.get('unknown_markers', [])))
        check('Unknown Alpha' in all_unk, "'Unknown Alpha' tracked")
        check('Unknown Beta'  in all_unk, "'Unknown Beta' tracked")
        check(len(all_unk) == 2, f"2 unique unknowns (got {len(all_unk)}: {all_unk})")
    finally: _rm(lf)


def test_parse_repeated_unknown_deduped():
    heading("_parse_lyrics — same unknown repeated, deduped in set")
    lf = _lf("[Unknown Alpha]\nL1\n[Unknown Alpha]\nL2\n[Unknown Alpha]\nL3\n")
    try:
        lines = _parse_lyrics(lf)
        unk_set = set(m for l in lines for m in l.get('unknown_markers', []))
        check('Unknown Alpha' in unk_set, "Unknown Alpha present")
        check(len(unk_set) == 1, f"Deduped to 1 (got {len(unk_set)})")
    finally: _rm(lf)


def test_parse_known_after_unknown_restores_style():
    heading("_parse_lyrics — known marker after unknown restores correct style")
    lf = _lf("[Unknown Section]\nL1\n[Chorus]\nL2\n[Unknown Again]\nL3\n[Bridge]\nL4\n")
    try:
        lines = _parse_lyrics(lf)
        _, s1 = _resolve_section(lines[1]['section'])
        _, s3 = _resolve_section(lines[3]['section'])
        check(s1 == 'chorus', f"After [Chorus] -> chorus (got {s1})")
        check(s3 == 'bridge', f"After [Bridge] -> bridge (got {s3})")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _parse_lyrics — inline stripping
# -----------------------------------------------------------------

def test_parse_inline_parens_stripped():
    heading("_parse_lyrics — inline (directions) stripped")
    lf = _lf("[Chorus]\n(Please stop) Cause Im here (backing vocal)\nOh Fuck (screaming)\n")
    try:
        lines = _parse_lyrics(lf)
        for line in lines:
            check('(' not in line['text'] and ')' not in line['text'],
                  f"No parens in '{line['text']}'")
    finally: _rm(lf)


def test_parse_inline_brackets_stripped():
    heading("_parse_lyrics — inline [directions] stripped")
    lf = _lf("[Chorus]\n[Scream] It hurts like hell [fade out]\nLine [annotation] here\n")
    try:
        lines = _parse_lyrics(lf)
        for line in lines:
            check('[' not in line['text'] and ']' not in line['text'],
                  f"No brackets in '{line['text']}'")
    finally: _rm(lf)


def test_parse_apostrophes_preserved():
    heading("_parse_lyrics — contractions preserved after stripping")
    lf = _lf("[Chorus]\nI'm still here (backing vocals)\nDon't give up\nIt's my fate\n")
    try:
        lines = _parse_lyrics(lf)
        texts = " ".join(l['text'] for l in lines)
        for word in ["I'm", "Don't", "It's"]:
            check(word in texts, f"'{word}' preserved")
    finally: _rm(lf)


def test_parse_purely_inline_line_skipped():
    heading("_parse_lyrics — line that is ONLY inline direction -> skipped")
    lf = _lf("[Verse]\n(backing vocals only)\n[Chorus]\nActual lyric here\n(adlib)\n")
    try:
        lines = _parse_lyrics(lf)
        texts = [l['text'] for l in lines]
        check(all('(' not in t for t in texts), "No paren-only lines retained")
        check('Actual lyric here' in texts, "'Actual lyric here' kept")
        check(len(lines) == 1, f"Only 1 singable line (got {len(lines)})")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _parse_lyrics — non-singable lines
# -----------------------------------------------------------------

def test_parse_punctuation_only_skipped():
    heading("_parse_lyrics — punctuation-only lines skipped")
    lf = _lf("[Verse]\nActual words\n... ... ...\n--- --- ---\n!!! ??? ###\nMore words\n")
    try:
        lines = _parse_lyrics(lf)
        for line in lines:
            check(bool(re.search(r'[a-zA-Z]', line['text'])),
                  f"'{line['text']}' has alphabetic content")
    finally: _rm(lf)


def test_parse_empty_file():
    heading("_parse_lyrics — empty file -> 0 lines")
    lf = _lf("")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 0, f"0 lines (got {len(lines)})")
    finally: _rm(lf)


def test_parse_markers_only():
    heading("_parse_lyrics — markers-only file -> 0 lines")
    lf = _lf("[Intro]\n[Verse]\n[Chorus]\n[Bridge]\n[Outro]\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 0, f"0 lines (got {len(lines)})")
    finally: _rm(lf)


def test_parse_stage_directions_only():
    heading("_parse_lyrics — stage-directions-only file -> 0 lines")
    lf = _lf("[Heavy Wall of Sound Loud]\n[Slow tempo guitar riff enters]\n[Drums kick in hard]\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 0, f"0 lines (got {len(lines)})")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _parse_lyrics — unicode and encoding
# -----------------------------------------------------------------

def test_parse_unicode_text():
    heading("_parse_lyrics — unicode characters in lyric text")
    lf = _lf("[Verse]\nCafé au lait\nNiña bonita\nÄpfel und Birnen\n[Chorus]\nÔ belle vie\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 4, f"4 lines (got {len(lines)})")
        texts = " ".join(l['text'] for l in lines)
        for snippet in ["Café", "Niña", "Äpfel", "belle"]:
            check(snippet in texts, f"'{snippet}' preserved")
    finally: _rm(lf)


def test_parse_unicode_section_markers():
    heading("_parse_lyrics — unicode section markers")
    lf = _lf("[refrão]\nL1\n[estrofe]\nL2\n[ponte]\nL3\n")
    try:
        lines = _parse_lyrics(lf)
        check(len(lines) == 3, f"3 lines (got {len(lines)})")
        _, s0 = _resolve_section(lines[0]['section'])
        check(s0 == 'chorus', f"refrão -> chorus (got {s0})")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _parse_lyrics — Suno-specific patterns
# -----------------------------------------------------------------

def test_parse_suno_full_pattern():
    heading("_parse_lyrics — Suno full-song pattern with mixed directions")
    lf = _lf("""[Intro]
[Long Instrumental Intro]
[Ambient wind sound]
Still

[Verse]
[Slow Heavy Groove]
[Monotone Vocal]
This iron drinks the life
I made this bed of stone

[Pre-Chorus]
[Dissonant Guitar Feedback]
A wrench in the gears
Grinding the fear

[Chorus]
[Explosion]
[Heavy Wall of Sound]
[Raw Scream]
Cause Im still here
Choking on fear

[Bridge]
[Chaotic Breakdown]
[Voice cracks with emotion]
Oh Fuck
It hurts like hell

[Outro]
[Maximum Volume]
I must carry on
""")
    try:
        lines = _parse_lyrics(lf)
        sections = set(l['section'] for l in lines)
        all_unk = set(m for l in lines for m in l.get('unknown_markers', []))
        texts = [l['text'] for l in lines]

        check(len(lines) >= 8, f"≥8 singable lines (got {len(lines)})")
        check(len(sections) >= 4, f"≥4 sections (got {sections})")
        check(len(all_unk) == 0, f"0 unknown markers (got {all_unk})")
        check('Still' in texts, "'Still' preserved")
        check('I must carry on' in texts, "'I must carry on' preserved")
        for line in lines:
            check('[' not in line['text'] and '(' not in line['text'],
                  f"No brackets in '{line['text'][:40]}'")
    finally: _rm(lf)


def test_parse_suno_adlib_patterns():
    heading("_parse_lyrics — Suno adlib/backing stripped")
    lf = _lf("""[Chorus]
(adbl
Cause Im still here
(Please stop move)
Cannot catch a breath
(This is the path you choose)
Carry on
""")
    try:
        lines = _parse_lyrics(lf)
        for line in lines:
            check('(' not in line['text'] and ')' not in line['text'],
                  f"Adlib stripped: '{line['text']}'")
    finally: _rm(lf)


# -----------------------------------------------------------------
# _build_full_text
# -----------------------------------------------------------------

def test_build_ordering():
    heading("_build_full_text — preserves line order")
    lines = [{"text":"first","section":"verse"},{"text":"second","section":"chorus"},
             {"text":"third","section":"bridge"}]
    result = _build_full_text(lines)
    check(result == "first second third", f"Correct order: '{result}'")


def test_build_single_line():
    heading("_build_full_text — single line")
    result = _build_full_text([{"text":"just this","section":"verse"}])
    check(result == "just this", f"Single: '{result}'")


def test_build_empty():
    heading("_build_full_text — empty input")
    result = _build_full_text([])
    check(result == "", f"Empty -> '' (got '{result}')")


def test_build_contractions():
    heading("_build_full_text — contractions preserved in join")
    lines = [{"text":"I'm here","section":"chorus"},{"text":"don't stop","section":"chorus"}]
    result = _build_full_text(lines)
    check("I'm" in result, "I'm preserved")
    check("don't" in result, "don't preserved")


# -----------------------------------------------------------------
# _split_words_by_lines
# -----------------------------------------------------------------

def test_split_basic():
    heading("_split_words_by_lines — basic alignment")
    lyric_lines = [{"text":"Still","section":"intro"},
                   {"text":"Breathing","section":"verse"},
                   {"text":"Running on","section":"verse"}]
    words = [_w("Still",24.0,24.5),_w("Breathing",38.0,38.8),
             _w("Running",41.0,41.4),_w("on",41.4,41.7)]
    segs = _split_words_by_lines(lyric_lines, words)
    check(len(segs) == 3, f"3 segments (got {len(segs)})")
    check(segs[0]['text'] == 'Still', f"seg 0 text (got '{segs[0]['text']}')")
    check(segs[0]['section'] == 'intro', f"seg 0 section")
    check(len(segs[0]['words']) == 1, f"seg 0: 1 word")
    check(len(segs[2]['words']) == 2, f"seg 2: 2 words")


def test_split_timestamps_preserved():
    heading("_split_words_by_lines — timestamps carried through")
    lyric_lines = [{"text":"Cause Im here","section":"chorus"}]
    words = [_w("Cause",64.0,64.5),_w("Im",64.5,64.9),_w("here",64.9,70.0)]
    segs = _split_words_by_lines(lyric_lines, words)
    check(segs[0]['start'] == 64.0, f"seg start = 64.0 (got {segs[0]['start']})")
    check(segs[0]['end']   == 70.0, f"seg end = 70.0 (got {segs[0]['end']})")
    check(segs[0]['words'][0]['start'] == 64.0, "word 0 start preserved")
    check(segs[0]['words'][2]['end']   == 70.0, "word 2 end preserved")


def test_split_fewer_words_than_expected():
    heading("_split_words_by_lines — fewer words than lyrics expects -> no crash")
    lyric_lines = [{"text":"one two three","section":"verse"},
                   {"text":"four five","section":"verse"}]
    words = [_w("one",1.0,1.5),_w("two",1.5,2.0),_w("three",2.0,2.5)]
    try:
        segs = _split_words_by_lines(lyric_lines, words)
        check(len(segs) >= 1, f"≥1 segment produced (no crash)")
        check(segs[0]['text'] == 'one two three', f"First segment correct")
    except Exception as e:
        _fail(f"Raised exception: {e}")


def test_split_extra_words_not_forced():
    heading("_split_words_by_lines — extra words not forced into segments")
    lyric_lines = [{"text":"one","section":"verse"}]
    words = [_w("one",1.0,1.5),_w("extra",1.5,2.0),_w("more",2.0,2.5)]
    segs = _split_words_by_lines(lyric_lines, words)
    check(len(segs) == 1, f"1 segment (got {len(segs)})")
    check(len(segs[0]['words']) == 1, f"1 word in segment (got {len(segs[0]['words'])})")


def test_split_score_to_probability():
    heading("_split_words_by_lines — score -> probability")
    lyric_lines = [{"text":"test","section":"verse"}]
    words = [_w("test",1.0,1.5,score=0.87)]
    segs = _split_words_by_lines(lyric_lines, words)
    check(segs[0]['words'][0]['probability'] == 0.87,
          f"probability = 0.87 (got {segs[0]['words'][0]['probability']})")


def test_split_section_in_output():
    heading("_split_words_by_lines — section label in output segments")
    lyric_lines = [{"text":"chorus line","section":"chorus"},
                   {"text":"bridge line","section":"bridge"}]
    words = [_w("chorus",1.0,1.5),_w("line",1.5,2.0),
             _w("bridge",3.0,3.5),_w("line",3.5,4.0)]
    segs = _split_words_by_lines(lyric_lines, words)
    check(segs[0]['section'] == 'chorus', f"seg 0 -> chorus (got '{segs[0]['section']}')")
    check(segs[1]['section'] == 'bridge', f"seg 1 -> bridge (got '{segs[1]['section']}')")


# -----------------------------------------------------------------
# _snap_to_onsets
# -----------------------------------------------------------------

def test_snap_basic():
    heading("_snap_to_onsets — word boundary snapped to nearest onset")
    segs = [_seg([_w("Cause",64.0,65.0)])]
    result, n = _snap_to_onsets(segs, [63.5,63.8,65.1], snap_window=1.5)
    check(n >= 1, f"≥1 correction applied (got {n})")
    new_start = result[0]['words'][0]['start']
    check(new_start == 63.8, f"Snapped to 63.8 (got {new_start})")


def test_snap_outside_window():
    heading("_snap_to_onsets — onset outside window -> no correction")
    segs = [_seg([_w("word",64.0,65.0)])]
    result, n = _snap_to_onsets(segs, [60.0,61.0,68.0], snap_window=1.5)
    check(n == 0, f"0 corrections (got {n})")
    check(result[0]['words'][0]['start'] == 64.0, "Start unchanged")


def test_snap_empty_onsets():
    heading("_snap_to_onsets — empty onsets -> no-op")
    segs = [_seg([_w("word",64.0,65.0)])]
    result, n = _snap_to_onsets(segs, [], snap_window=1.5)
    check(n == 0, f"0 corrections (got {n})")
    check(result[0]['words'][0]['start'] == 64.0, "Start unchanged")


def test_snap_inversion_guard():
    heading("_snap_to_onsets — snap that would invert start/end is rejected")
    # onset at 64.5 > end 64.3 -> would invert
    segs = [_seg([_w("word",64.0,64.3)])]
    result, n = _snap_to_onsets(segs, [64.5], snap_window=1.5)
    check(n == 0, "Inverting snap rejected")
    check(result[0]['words'][0]['start'] == 64.0, "Start unchanged")


def test_snap_overlap_prev_guard():
    heading("_snap_to_onsets — snap that overlaps previous word rejected")
    segs = [_seg([_w("prev",63.0,64.0),_w("this",64.5,65.0)])]
    # onset at 63.8 < prev_end (64.0) + min_word_dur (0.05) = 64.05
    result, n = _snap_to_onsets(segs, [63.8], snap_window=1.5)
    check(result[0]['words'][1]['start'] == 64.5,
          "Overlapping snap rejected, start unchanged")


def test_snap_segment_start_updated():
    heading("_snap_to_onsets — segment.start updated after first-word snap")
    segs = [_seg([_w("Cause",64.0,64.5),_w("Im",64.5,65.0)])]
    result, n = _snap_to_onsets(segs, [63.8], snap_window=1.5)
    if n > 0:
        check(result[0]['start'] == result[0]['words'][0]['start'],
              "Segment start == first word start after snap")


def test_snap_zero_window_disables():
    heading("_snap_to_onsets — snap_window=0 disables all corrections")
    segs = [_seg([_w("word",64.0,65.0)])]
    result, n = _snap_to_onsets(segs, [64.1], snap_window=0.0)
    check(n == 0, f"0 corrections with snap_window=0 (got {n})")


def test_snap_negligible_delta_skipped():
    heading("_snap_to_onsets — delta < 0.01s skipped as negligible")
    segs = [_seg([_w("word",64.0,65.0)])]
    # onset at 64.005 — delta=0.005 < threshold 0.01
    result, n = _snap_to_onsets(segs, [64.005], snap_window=1.5)
    check(n == 0, "Negligible delta not applied")


# -----------------------------------------------------------------
# PROPERTY-BASED
# -----------------------------------------------------------------

def test_property_resolve_always_valid_style():
    heading("PROPERTY: _resolve_section always returns a valid ASS style")
    valid_styles = supported_style_keys()
    test_labels = list(SECTION_TO_STYLE.keys()) + [
        "unknown xyz","chorus 99","verse 100","drop 5","refra xyz",
        "pont test","build test","pre test","intro xyz","outro xyz",
        "","  ","---",
    ]
    for label in test_labels:
        try:
            _, style = _resolve_section(label)
            check(style in valid_styles,
                  f"'{label[:30]}' -> valid style '{style}'",
                  f"invalid style '{style}'")
        except Exception as e:
            _fail(f"'{label[:30]}' raised: {e}")


def test_property_parse_output_always_singable():
    heading("PROPERTY: _parse_lyrics lines always have alphabetic text")
    test_inputs = [
        "[Verse]\nLine one\n... ... ...\n12345\nLine two\n",
        "[Chorus]\n\n\nCause Im here\n(adlib)\n",
        "No markers at all\nJust text\n",
    ]
    for content in test_inputs:
        lf = _lf(content)
        try:
            lines = _parse_lyrics(lf)
            for line in lines:
                check(bool(re.search(r'[a-zA-Z\u00C0-\u024F]', line['text'])),
                      f"Alpha content: '{line['text'][:40]}'")
        finally: _rm(lf)


# -----------------------------------------------------------------
# REGRESSION
# -----------------------------------------------------------------

def test_struggle_regression():
    heading("REGRESSION: Struggle lyrics.txt end-to-end")
    struggle = Path(__file__).parent.parent / "jobs" / "struggle_test" / "lyrics.txt"
    if not struggle.exists():
        print("  (skipped — jobs/struggle_test/lyrics.txt not found)")
        return

    lines = _parse_lyrics(struggle)
    sections = set(l['section'] for l in lines)
    all_unk = sorted(set(m for l in lines for m in l.get('unknown_markers', [])))
    full = _build_full_text(lines)

    check(len(lines) >= 50,  f"≥50 lines (got {len(lines)})")
    check(len(lines) <= 200, f"≤200 lines — not exploding (got {len(lines)})")
    check(len(sections) > 1, f">1 sections (got {sections})")
    check(len(all_unk) == 0, f"0 unknown markers (got {all_unk})")

    for line in lines:
        check('[' not in line['text'] and '(' not in line['text'],
              f"No brackets in '{line['text'][:40]}'")

    for word in ["here","still","fear","will"]:
        check(word in full.lower(), f"'{word}' in full text")

    # Style distribution via _resolve_section
    styles = {_resolve_section(l['section'])[1] for l in lines}
    check(len(styles) > 1, f"Multiple styles (got {styles})")

    print(f"  (Struggle: {len(lines)} lines, {len(sections)} sections, {len(styles)} ASS styles)")


# -----------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------

def main() -> int:
    global _verbose
    parser = argparse.ArgumentParser(description="Comprehensive lyric robustness tests")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    _verbose = args.verbose

    print(f"\n{'='*62}")
    print(f"  test_lyrics_robustness.py — comprehensive suite")
    print(f"{'='*62}")

    # _resolve_section
    test_resolve_exact_all_55_entries()
    test_resolve_numeric_strip()
    test_resolve_all_prefix_fallbacks()
    test_resolve_unknown_defaults_verse()
    test_resolve_edge_cases()
    test_resolve_all_keys_are_lowercase()
    test_resolve_unicode()

    # _is_stage_direction
    test_stage_known_sections_never_direction()
    test_stage_word_count_threshold()
    test_stage_keywords_trigger()
    test_stage_false_negatives_avoided()
    test_stage_exactly_four_words()
    test_stage_property_always_bool()

    # _parse_lyrics — sections
    test_parse_basic()
    test_parse_section_persists_multi_line()
    test_parse_section_persists_across_blanks()
    test_parse_no_markers_defaults_verse()
    test_parse_numbered_markers()
    test_parse_pt_es_edm_markers()
    test_parse_mixed_case_markers()
    test_parse_consecutive_markers_no_text()

    # _parse_lyrics — directions
    test_parse_verbose_directions_skipped()
    test_parse_direction_doesnt_corrupt_section()

    # _parse_lyrics — unknowns
    test_parse_unknown_tracked()
    test_parse_multiple_unknowns_accumulated()
    test_parse_repeated_unknown_deduped()
    test_parse_known_after_unknown_restores_style()

    # _parse_lyrics — stripping
    test_parse_inline_parens_stripped()
    test_parse_inline_brackets_stripped()
    test_parse_apostrophes_preserved()
    test_parse_purely_inline_line_skipped()

    # _parse_lyrics — non-singable
    test_parse_punctuation_only_skipped()
    test_parse_empty_file()
    test_parse_markers_only()
    test_parse_stage_directions_only()

    # _parse_lyrics — encoding
    test_parse_unicode_text()
    test_parse_unicode_section_markers()

    # _parse_lyrics — Suno patterns
    test_parse_suno_full_pattern()
    test_parse_suno_adlib_patterns()

    # _build_full_text
    test_build_ordering()
    test_build_single_line()
    test_build_empty()
    test_build_contractions()

    # _split_words_by_lines
    test_split_basic()
    test_split_timestamps_preserved()
    test_split_fewer_words_than_expected()
    test_split_extra_words_not_forced()
    test_split_score_to_probability()
    test_split_section_in_output()

    # _snap_to_onsets
    test_snap_basic()
    test_snap_outside_window()
    test_snap_empty_onsets()
    test_snap_inversion_guard()
    test_snap_overlap_prev_guard()
    test_snap_segment_start_updated()
    test_snap_zero_window_disables()
    test_snap_negligible_delta_skipped()

    # Properties
    test_property_resolve_always_valid_style()
    test_property_parse_output_always_singable()

    # Regression
    test_struggle_regression()

    total = _passed + _failed
    print(f"\n{'='*62}")
    if _failed == 0:
        print(f"  {_G}PASSED{_X}  {_passed}/{total} tests")
    else:
        print(f"  {_R}FAILED{_X}  {_failed}/{total} tests failed")
    print(f"{'='*62}\n")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
