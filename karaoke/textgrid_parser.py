"""
textgrid_parser.py — Pure TextGrid parsing functions.
No subprocess, no file I/O implicit side-effects beyond reading the file.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional


# Tokens that MFA inserts as "silence" markers — NOT real words
SILENCE_TOKENS = frozenset({"sp", "spn", "sil", "<eps>", ""})

# Tier names preferred (in priority order) for the word tier
WORD_TIER_PRIORITY = ["words", "word", "Word", "WORDS", "transcript"]


@dataclass
class Interval:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start

@dataclass
class WordMapping:
    """A word and its component phonemes from the phones tier."""
    word: Interval
    phones: List[Interval] = field(default_factory=list)


@dataclass
class Tier:
    name: str
    intervals: List[Interval] = field(default_factory=list)

    @property
    def speech_intervals(self) -> List[Interval]:
        """Return only non-silence, non-empty intervals."""
        return [i for i in self.intervals if i.text.strip() not in SILENCE_TOKENS]


def parse_textgrid(content: str) -> List[Tier]:
    """
    Parse a Praat TextGrid (full-text format) string.
    Returns a list of Tier objects (only IntervalTiers).
    """
    tier_blocks = re.split(r'class = "IntervalTier"', content)[1:]
    tiers: List[Tier] = []

    for block in tier_blocks:
        name_match = re.search(r'name = "(.*?)"', block)
        if not name_match:
            continue
        tier_name = name_match.group(1)

        raw_intervals = re.findall(
            r'intervals \[\d+\]:\s*xmin = ([\d\.]+)\s*xmax = ([\d\.]+)\s*text = "(.*?)"',
            block,
        )
        intervals = [
            Interval(start=float(xmin), end=float(xmax), text=text)
            for xmin, xmax, text in raw_intervals
        ]
        tiers.append(Tier(name=tier_name, intervals=intervals))

    return tiers


def list_tier_names(tiers: List[Tier]) -> List[str]:
    """Return ordered list of tier names."""
    return [t.name for t in tiers]


def select_word_tier(tiers: List[Tier]) -> Tier:
    """
    Choose the best word-level tier using a priority list, then a
    count-based heuristic as fallback.

    Raises ValueError if no tier has any speech intervals.
    """
    # Priority pass
    for preferred in WORD_TIER_PRIORITY:
        for tier in tiers:
            if tier.name == preferred and tier.speech_intervals:
                return tier

    # Heuristic fallback: tier with most speech intervals
    ranked = sorted(tiers, key=lambda t: len(t.speech_intervals), reverse=True)
    if ranked and ranked[0].speech_intervals:
        return ranked[0]

    raise ValueError(
        "No speech intervals found in any tier. "
        "Check TextGrid content or MFA alignment."
    )


def extract_words(tg_content: str) -> List[Interval]:
    """
    High-level convenience: parse TextGrid, select word tier, return
    speech intervals sorted by start time.
    """
    tiers = parse_textgrid(tg_content)
    tier = select_word_tier(tiers)
    words = sorted(tier.speech_intervals, key=lambda i: i.start)
    return words


def extract_words_and_phones(tg_content: str) -> List[WordMapping]:
    """
    Parse both 'words' and 'phones' tiers and associate each phone with its parent word.
    """
    tiers = parse_textgrid(tg_content)
    
    word_tier_obj = None
    phone_tier_obj = None
    
    for tier in tiers:
        if tier.name in WORD_TIER_PRIORITY:
            word_tier_obj = tier
        if tier.name == "phones":
            phone_tier_obj = tier
            
    if not word_tier_obj:
        word_tier_obj = select_word_tier(tiers) # fallback
        
    words = sorted(word_tier_obj.speech_intervals, key=lambda i: i.start)
    
    if not phone_tier_obj:
        return [WordMapping(word=w, phones=[]) for w in words]
        
    phones = sorted(phone_tier_obj.intervals, key=lambda i: i.start) # Include empty/silence phones to be safe
    
    mappings: List[WordMapping] = []
    p_idx = 0
    num_phones = len(phones)
    
    for w in words:
        w_phones = []
        # Find all phones that overlap significantly with this word
        # In MFA, phones are strictly contained within words
        while p_idx < num_phones:
            p = phones[p_idx]
            # If phone starts after word, we are done for this word
            if p.start >= w.end - 0.001:
                break
            
            # If phone ends before word starts, skip it
            if p.end <= w.start + 0.001:
                p_idx += 1
                continue
            
            # If it's a silence phone inside a word (unusual), we might skip it or keep it
            # For karaoke animation, we keep it to maintain timing
            w_phones.append(p)
            p_idx += 1
            
        # Rewind p_idx slightly because the loop might have gone one too far
        # or we might share a boundary. But in MFA, phones are disjoint.
        # Actually p_idx is fine where it is for the next word.
        
        mappings.append(WordMapping(word=w, phones=w_phones))
        
    return mappings


def serialize_textgrid(tiers: List[Tier], xmin: float, xmax: float) -> str:
    """
    Serialize a list of Tier objects back into Praat TextGrid format.
    """
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        '',
        f'xmin = {xmin}',
        f'xmax = {xmax}',
        'tiers? <exists>',
        f'size = {len(tiers)}',
        'item []:'
    ]
    
    for i, tier in enumerate(tiers, 1):
        lines.append(f'    item [{i}]:')
        lines.append(f'        class = "IntervalTier"')
        lines.append(f'        name = "{tier.name}"')
        lines.append(f'        xmin = {xmin}')
        lines.append(f'        xmax = {xmax}')
        lines.append(f'        intervals: size = {len(tier.intervals)}')
        for j, iv in enumerate(tier.intervals, 1):
            lines.append(f'        intervals [{j}]:')
            lines.append(f'            xmin = {iv.start}')
            lines.append(f'            xmax = {iv.end}')
            lines.append(f'            text = "{iv.text}"')
            
    return '\n'.join(lines) + '\n'
