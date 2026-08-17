"""Pure style definitions and helpers for karaoke subtitle stages."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping

DEFAULT_STYLE_KEY = "verse"
# What a line may ask for. "flash" is not here: it is a style property
# (KaraokeStyle.highlight_effect), not something a line picks.
SUPPORTED_EFFECTS = ("highlight", "none")


@dataclass(frozen=True)
class KaraokeStyle:
    r"""
    One ASS style definition. Field names are designer-facing intent;
    s06's _generate_ass swaps primary/secondary onto the ASS Style line
    because libass sweeps \kf from SecondaryColour to PrimaryColour.
    primary_color   = not-yet-sung text color   (written to \2c)  &HBBGGRR&
    secondary_color = progressive fill color    (written to \1c)  filled by \kf
    outline_color   = border                    (\3c)
    back_color      = shadow/background         (\4c)
    """

    name: str
    fontname: str
    fontsize: int
    bold: bool
    italic: bool
    primary_color: str
    secondary_color: str
    outline_color: str
    back_color: str
    outline: float
    shadow: float
    alignment: int
    margin_v: int
    border_style: int = 1
    highlight_effect: str = "highlight"


@dataclass(frozen=True)
class StylePreset:
    id: str
    label: str
    version: int
    description: str
    styles: Mapping[str, KaraokeStyle]
    effects: tuple[str, ...] = SUPPORTED_EFFECTS


def _c(r: int, g: int, b: int, a: int = 0) -> str:
    """Convert RGBA to ASS &HAABBGGRR format."""
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


DEFAULT_STYLES: dict[str, KaraokeStyle] = {
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(220, 220, 220),
        secondary_color=_c(0, 220, 255),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.5,
        alignment=2,
        margin_v=40,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(235, 235, 235),
        secondary_color=_c(255, 205, 0),
        outline_color=_c(70, 50, 0),
        back_color=_c(0, 0, 0, 76),
        outline=2.6,
        shadow=1.5,
        alignment=2,
        margin_v=40,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(0, 200, 255),
        outline_color=_c(0, 60, 120),
        back_color=_c(0, 0, 0, 60),
        outline=3.0,
        shadow=2.0,
        alignment=2,
        margin_v=40,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=50,
        bold=True,
        italic=True,
        primary_color=_c(210, 210, 255),
        secondary_color=_c(200, 100, 255),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.5,
        alignment=2,
        margin_v=40,
    ),
    # intro/outro stay understated, but the sung fill is now a muted cyan from
    # the preset's own palette instead of a 20-step of the same gray: the old
    # 180->200 pair had no hue and no brightness, so the sweep did not read.
    # cyberpunk aliases both of these, so it inherits the fix.
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=40,
        bold=False,
        italic=False,
        primary_color=_c(215, 215, 215),
        secondary_color=_c(80, 150, 175),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 100),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=40,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 235, 215),
        secondary_color=_c(255, 120, 30),
        outline_color=_c(85, 32, 0),
        back_color=_c(0, 0, 0, 70),
        outline=3.0,
        shadow=1.8,
        alignment=2,
        margin_v=40,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=40,
        bold=False,
        italic=False,
        primary_color=_c(215, 215, 215),
        secondary_color=_c(80, 150, 175),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 100),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=40,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(230, 230, 230),
        secondary_color=_c(120, 200, 255),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 80),
        outline=2.2,
        shadow=0.8,
        alignment=2,
        margin_v=40,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Bold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(200, 255, 200),
        secondary_color=_c(50, 255, 100),
        outline_color=_c(0, 60, 0),
        back_color=_c(0, 0, 0, 100),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=40,
    ),
}

NEON_STYLES: dict[str, KaraokeStyle] = {
    k: KaraokeStyle(
        name=v.name,
        fontname="Segoe UI Bold",
        fontsize=v.fontsize + 4,
        bold=True,
        italic=v.italic,
        primary_color=_c(40, 40, 40),
        secondary_color=_c(0, 255, 180),
        outline_color=_c(0, 200, 120),
        back_color=_c(0, 0, 0, 60),
        outline=3.0,
        shadow=0.0,
        alignment=v.alignment,
        margin_v=v.margin_v,
    )
    for k, v in DEFAULT_STYLES.items()
}

NEON_STYLES["chorus"] = KaraokeStyle(
    name="Chorus",
    fontname="Segoe UI Bold",
    fontsize=68,
    bold=True,
    italic=False,
    primary_color=_c(60, 60, 60),
    secondary_color=_c(255, 220, 0),
    outline_color=_c(180, 140, 0),
    back_color=_c(0, 0, 0, 60),
    outline=3.5,
    shadow=0.0,
    alignment=2,
    margin_v=40,
)

NEON_STYLES["prechorus"] = KaraokeStyle(
    name="PreChorus",
    fontname="Segoe UI Bold",
    fontsize=60,
    bold=True,
    italic=False,
    primary_color=_c(50, 50, 50),
    secondary_color=_c(0, 255, 255),
    outline_color=_c(0, 190, 190),
    back_color=_c(0, 0, 0, 60),
    outline=3.0,
    shadow=0.0,
    alignment=2,
    margin_v=40,
)

NEON_STYLES["drop"] = KaraokeStyle(
    name="Drop",
    fontname="Segoe UI Bold",
    fontsize=64,
    bold=True,
    italic=False,
    primary_color=_c(55, 55, 55),
    secondary_color=_c(255, 110, 0),
    outline_color=_c(170, 70, 0),
    back_color=_c(0, 0, 0, 60),
    outline=3.2,
    shadow=0.0,
    alignment=2,
    margin_v=40,
)

NEON_STYLES["rap"] = KaraokeStyle(
    name="Rap",
    fontname="Segoe UI Bold",
    fontsize=48,
    bold=False,
    italic=False,
    primary_color=_c(45, 45, 45),
    secondary_color=_c(170, 255, 60),
    outline_color=_c(110, 190, 30),
    back_color=_c(0, 0, 0, 60),
    outline=2.6,
    shadow=0.0,
    alignment=2,
    margin_v=40,
)

CYBERPUNK_STYLES: dict[str, KaraokeStyle] = {
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(123, 47, 190),
        secondary_color=_c(0, 245, 255),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 150),
        outline=2.5,
        shadow=1.5,
        alignment=2,
        margin_v=50,
        border_style=3,
        highlight_effect="flash",
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(150, 60, 205),
        secondary_color=_c(255, 240, 60),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 150),
        outline=2.6,
        shadow=1.5,
        alignment=2,
        margin_v=50,
        border_style=3,
        highlight_effect="flash",
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(0, 245, 255),
        outline_color=_c(123, 47, 190),
        back_color=_c(0, 0, 0, 150),
        outline=3.0,
        shadow=2.0,
        alignment=2,
        margin_v=50,
        border_style=3,
        highlight_effect="flash",
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(180, 0, 180),
        secondary_color=_c(255, 255, 255),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 150),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=50,
        border_style=3,
        highlight_effect="highlight",
    ),
    "intro": DEFAULT_STYLES["intro"],
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(255, 0, 140),
        outline_color=_c(90, 0, 60),
        back_color=_c(0, 0, 0, 150),
        outline=3.0,
        shadow=1.8,
        alignment=2,
        margin_v=50,
        border_style=3,
        highlight_effect="flash",
    ),
    "outro": DEFAULT_STYLES["outro"],
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(210, 190, 235),
        secondary_color=_c(120, 255, 220),
        outline_color=_c(0, 0, 0),
        back_color=_c(0, 0, 0, 150),
        outline=2.2,
        shadow=1.0,
        alignment=2,
        margin_v=50,
        border_style=3,
    ),
    "ad_lib": DEFAULT_STYLES["ad_lib"],
}

SECTION_CODED_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(190, 220, 220),
        secondary_color=_c(90, 210, 220),
        outline_color=_c(0, 40, 48),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        # Waiting text is a cool gray, not near-white: the old 245->255 pair
        # was a luminance ratio of 1.09 with no hue shift either, so the \kf
        # sweep was invisible. Verse stays the neutral section, but the fill
        # now reads as a step in brightness.
        primary_color=_c(168, 176, 190),
        secondary_color=_c(255, 255, 255),
        outline_color=_c(20, 20, 20),
        back_color=_c(0, 0, 0, 80),
        outline=2.4,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=54,
        bold=True,
        italic=False,
        primary_color=_c(255, 245, 190),
        secondary_color=_c(255, 220, 40),
        outline_color=_c(70, 54, 0),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 235, 248),
        secondary_color=_c(255, 70, 190),
        outline_color=_c(90, 0, 52),
        back_color=_c(0, 0, 0, 70),
        outline=3.0,
        shadow=1.6,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(220, 255, 225),
        secondary_color=_c(80, 220, 120),
        outline_color=_c(0, 55, 20),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 235, 210),
        secondary_color=_c(255, 130, 40),
        outline_color=_c(80, 34, 0),
        back_color=_c(0, 0, 0, 80),
        outline=3.0,
        shadow=1.4,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(190, 205, 235),
        secondary_color=_c(110, 150, 220),
        outline_color=_c(0, 25, 70),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(230, 230, 235),
        secondary_color=_c(120, 200, 255),
        outline_color=_c(10, 10, 20),
        back_color=_c(0, 0, 0, 80),
        outline=2.4,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": DEFAULT_STYLES["ad_lib"],
}

_SINGLE_STYLE_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Bold",
    fontsize=54,
    bold=True,
    italic=False,
    primary_color=_c(255, 248, 232),
    secondary_color=_c(255, 214, 92),
    outline_color=_c(84, 52, 5),
    back_color=_c(0, 0, 0, 78),
    outline=2.4,
    shadow=1.2,
    alignment=2,
    margin_v=42,
)

SINGLE_STYLE_KF_STYLES: dict[str, KaraokeStyle] = {
    key: KaraokeStyle(
        name=SECTION_CODED_STYLES.get(key, _SINGLE_STYLE_BASE).name,
        fontname=_SINGLE_STYLE_BASE.fontname,
        fontsize=_SINGLE_STYLE_BASE.fontsize,
        bold=_SINGLE_STYLE_BASE.bold,
        italic=_SINGLE_STYLE_BASE.italic,
        primary_color=_SINGLE_STYLE_BASE.primary_color,
        secondary_color=_SINGLE_STYLE_BASE.secondary_color,
        outline_color=_SINGLE_STYLE_BASE.outline_color,
        back_color=_SINGLE_STYLE_BASE.back_color,
        outline=_SINGLE_STYLE_BASE.outline,
        shadow=_SINGLE_STYLE_BASE.shadow,
        alignment=_SINGLE_STYLE_BASE.alignment,
        margin_v=_SINGLE_STYLE_BASE.margin_v,
        border_style=_SINGLE_STYLE_BASE.border_style,
        highlight_effect=_SINGLE_STYLE_BASE.highlight_effect,
    )
    for key in ("intro", "verse", "prechorus", "chorus", "bridge", "drop", "outro", "rap", "ad_lib")
}

AEGISUB_CLASSIC_BLUE_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(205, 225, 255),
        secondary_color=_c(110, 190, 255),
        outline_color=_c(0, 35, 95),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(245, 250, 255),
        secondary_color=_c(60, 205, 255),
        outline_color=_c(0, 38, 90),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(250, 252, 255),
        secondary_color=_c(90, 160, 255),
        outline_color=_c(0, 30, 100),
        back_color=_c(0, 0, 0, 76),
        outline=2.6,
        shadow=1.3,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(0, 240, 255),
        outline_color=_c(0, 78, 150),
        back_color=_c(0, 0, 0, 70),
        outline=3.0,
        shadow=1.6,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(225, 235, 255),
        secondary_color=_c(140, 180, 255),
        outline_color=_c(0, 35, 95),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 250, 240),
        secondary_color=_c(255, 190, 60),
        outline_color=_c(92, 58, 0),
        back_color=_c(0, 0, 0, 72),
        outline=3.0,
        shadow=1.5,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(190, 210, 240),
        secondary_color=_c(100, 160, 220),
        outline_color=_c(0, 30, 80),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(235, 242, 250),
        secondary_color=_c(120, 190, 235),
        outline_color=_c(0, 32, 72),
        back_color=_c(0, 0, 0, 80),
        outline=2.2,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Bold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(210, 245, 255),
        secondary_color=_c(80, 220, 255),
        outline_color=_c(0, 55, 80),
        back_color=_c(0, 0, 0, 100),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_GOLD_CHORUS_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Semibold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(235, 228, 205),
        secondary_color=_c(255, 215, 120),
        outline_color=_c(82, 48, 0),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Semibold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(255, 248, 232),
        secondary_color=_c(255, 214, 92),
        outline_color=_c(84, 52, 5),
        back_color=_c(0, 0, 0, 78),
        outline=2.4,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Semibold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(255, 240, 188),
        secondary_color=_c(255, 184, 36),
        outline_color=_c(98, 56, 0),
        back_color=_c(0, 0, 0, 76),
        outline=2.6,
        shadow=1.3,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=66,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 244),
        secondary_color=_c(255, 202, 28),
        outline_color=_c(122, 70, 0),
        back_color=_c(0, 0, 0, 70),
        outline=3.2,
        shadow=1.7,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Semibold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(240, 225, 255),
        secondary_color=_c(205, 160, 255),
        outline_color=_c(70, 34, 92),
        back_color=_c(0, 0, 0, 82),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=62,
        bold=True,
        italic=False,
        primary_color=_c(255, 244, 210),
        secondary_color=_c(255, 148, 48),
        outline_color=_c(110, 42, 0),
        back_color=_c(0, 0, 0, 76),
        outline=3.0,
        shadow=1.5,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Semibold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(222, 208, 180),
        secondary_color=_c(220, 164, 72),
        outline_color=_c(72, 44, 0),
        back_color=_c(0, 0, 0, 92),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Semibold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(245, 238, 222),
        secondary_color=_c(214, 178, 110),
        outline_color=_c(72, 44, 0),
        back_color=_c(0, 0, 0, 80),
        outline=2.2,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Semibold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(255, 238, 196),
        secondary_color=_c(255, 190, 70),
        outline_color=_c(96, 50, 0),
        back_color=_c(0, 0, 0, 100),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_ANIME_POP_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(255, 218, 245),
        secondary_color=_c(112, 230, 255),
        outline_color=_c(84, 22, 92),
        back_color=_c(0, 0, 0, 88),
        outline=2.1,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=54,
        bold=True,
        italic=False,
        primary_color=_c(255, 245, 252),
        secondary_color=_c(64, 220, 255),
        outline_color=_c(92, 20, 98),
        back_color=_c(0, 0, 0, 78),
        outline=2.6,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(255, 246, 198),
        secondary_color=_c(255, 230, 58),
        outline_color=_c(94, 58, 0),
        back_color=_c(0, 0, 0, 76),
        outline=2.6,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=66,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(255, 92, 202),
        outline_color=_c(112, 0, 80),
        back_color=_c(0, 0, 0, 70),
        outline=3.2,
        shadow=1.6,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(222, 236, 255),
        secondary_color=_c(150, 125, 255),
        outline_color=_c(48, 35, 110),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=62,
        bold=True,
        italic=False,
        primary_color=_c(220, 255, 250),
        secondary_color=_c(0, 255, 196),
        outline_color=_c(0, 88, 82),
        back_color=_c(0, 0, 0, 76),
        outline=3.0,
        shadow=1.4,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(245, 210, 232),
        secondary_color=_c(240, 120, 210),
        outline_color=_c(72, 18, 84),
        back_color=_c(0, 0, 0, 90),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(245, 240, 250),
        secondary_color=_c(120, 205, 255),
        outline_color=_c(70, 20, 80),
        back_color=_c(0, 0, 0, 80),
        outline=2.3,
        shadow=0.9,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Bold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(230, 255, 210),
        secondary_color=_c(130, 255, 80),
        outline_color=_c(38, 82, 0),
        back_color=_c(0, 0, 0, 100),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_SOFT_PASTEL_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Semibold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(224, 236, 232),
        secondary_color=_c(168, 218, 210),
        outline_color=_c(54, 78, 86),
        back_color=_c(0, 0, 0, 82),
        outline=1.8,
        shadow=0.9,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Semibold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(250, 248, 242),
        secondary_color=_c(160, 226, 204),
        outline_color=_c(58, 82, 88),
        back_color=_c(0, 0, 0, 72),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Semibold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(252, 246, 236),
        secondary_color=_c(232, 196, 142),
        outline_color=_c(84, 64, 44),
        back_color=_c(0, 0, 0, 72),
        outline=2.1,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Semibold",
        fontsize=62,
        bold=True,
        italic=False,
        primary_color=_c(255, 246, 250),
        secondary_color=_c(238, 170, 212),
        outline_color=_c(88, 58, 86),
        back_color=_c(0, 0, 0, 68),
        outline=2.3,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Semibold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(238, 232, 255),
        secondary_color=_c(188, 170, 236),
        outline_color=_c(62, 58, 94),
        back_color=_c(0, 0, 0, 74),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Semibold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(252, 240, 236),
        secondary_color=_c(236, 158, 142),
        outline_color=_c(92, 52, 44),
        back_color=_c(0, 0, 0, 70),
        outline=2.3,
        shadow=1.1,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Semibold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(224, 218, 230),
        secondary_color=_c(178, 170, 206),
        outline_color=_c(58, 60, 78),
        back_color=_c(0, 0, 0, 84),
        outline=1.8,
        shadow=0.9,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Semibold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(244, 244, 248),
        secondary_color=_c(172, 186, 214),
        outline_color=_c(58, 64, 82),
        back_color=_c(0, 0, 0, 78),
        outline=1.9,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Semibold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(232, 252, 222),
        secondary_color=_c(174, 230, 164),
        outline_color=_c(56, 82, 56),
        back_color=_c(0, 0, 0, 90),
        outline=1.8,
        shadow=0.9,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_NIGHT_GLOW_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(188, 210, 255),
        secondary_color=_c(105, 150, 255),
        outline_color=_c(8, 18, 68),
        back_color=_c(0, 0, 0, 95),
        outline=2.2,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(238, 244, 255),
        secondary_color=_c(98, 168, 255),
        outline_color=_c(10, 22, 76),
        back_color=_c(0, 0, 0, 84),
        outline=2.6,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(242, 246, 255),
        secondary_color=_c(120, 120, 255),
        outline_color=_c(18, 18, 86),
        back_color=_c(0, 0, 0, 80),
        outline=2.8,
        shadow=1.1,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(152, 92, 255),
        outline_color=_c(45, 16, 96),
        back_color=_c(0, 0, 0, 76),
        outline=3.2,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(218, 224, 255),
        secondary_color=_c(198, 122, 255),
        outline_color=_c(34, 18, 86),
        back_color=_c(0, 0, 0, 84),
        outline=2.6,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 246, 250),
        secondary_color=_c(255, 86, 190),
        outline_color=_c(92, 10, 62),
        back_color=_c(0, 0, 0, 76),
        outline=3.0,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(168, 188, 230),
        secondary_color=_c(98, 128, 210),
        outline_color=_c(8, 18, 68),
        back_color=_c(0, 0, 0, 96),
        outline=2.2,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(226, 234, 250),
        secondary_color=_c(110, 150, 205),
        outline_color=_c(10, 22, 76),
        back_color=_c(0, 0, 0, 84),
        outline=2.3,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Bold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(212, 244, 255),
        secondary_color=_c(74, 220, 255),
        outline_color=_c(0, 68, 96),
        back_color=_c(0, 0, 0, 100),
        outline=2.2,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_IMPACT_RED_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Black",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(214, 214, 214),
        secondary_color=_c(238, 88, 58),
        outline_color=_c(74, 0, 0),
        back_color=_c(0, 0, 0, 92),
        outline=2.4,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Black",
        fontsize=54,
        bold=True,
        italic=False,
        primary_color=_c(244, 244, 244),
        secondary_color=_c(235, 78, 52),
        outline_color=_c(78, 0, 0),
        back_color=_c(0, 0, 0, 82),
        outline=2.8,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Black",
        fontsize=58,
        bold=True,
        italic=False,
        primary_color=_c(250, 246, 240),
        secondary_color=_c(255, 196, 60),
        outline_color=_c(96, 60, 0),
        back_color=_c(0, 0, 0, 78),
        outline=3.0,
        shadow=1.4,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Black",
        fontsize=68,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(255, 46, 26),
        outline_color=_c(112, 0, 0),
        back_color=_c(0, 0, 0, 72),
        outline=3.5,
        shadow=1.8,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Black",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(220, 220, 220),
        secondary_color=_c(255, 132, 70),
        outline_color=_c(94, 28, 0),
        back_color=_c(0, 0, 0, 84),
        outline=2.8,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Black",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 232, 218),
        secondary_color=_c(255, 88, 0),
        outline_color=_c(116, 24, 0),
        back_color=_c(0, 0, 0, 76),
        outline=3.4,
        shadow=1.6,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Black",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(194, 194, 194),
        secondary_color=_c(196, 52, 40),
        outline_color=_c(72, 0, 0),
        back_color=_c(0, 0, 0, 94),
        outline=2.4,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Black",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(236, 236, 236),
        secondary_color=_c(198, 60, 44),
        outline_color=_c(66, 0, 0),
        back_color=_c(0, 0, 0, 84),
        outline=2.4,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Black",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(255, 220, 210),
        secondary_color=_c(255, 110, 76),
        outline_color=_c(90, 10, 0),
        back_color=_c(0, 0, 0, 100),
        outline=2.4,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_DUAL_VOCAL_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(198, 224, 238),
        secondary_color=_c(108, 210, 235),
        outline_color=_c(0, 58, 82),
        back_color=_c(0, 0, 0, 88),
        outline=2.1,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(248, 252, 255),
        secondary_color=_c(72, 224, 246),
        outline_color=_c(0, 72, 96),
        back_color=_c(0, 0, 0, 78),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(250, 252, 255),
        secondary_color=_c(110, 190, 255),
        outline_color=_c(0, 52, 96),
        back_color=_c(0, 0, 0, 76),
        outline=2.6,
        shadow=1.3,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(0, 198, 255),
        outline_color=_c(0, 78, 112),
        back_color=_c(0, 0, 0, 72),
        outline=3.0,
        shadow=1.5,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(238, 226, 255),
        secondary_color=_c(184, 128, 255),
        outline_color=_c(62, 28, 98),
        back_color=_c(0, 0, 0, 80),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 248, 236),
        secondary_color=_c(255, 176, 60),
        outline_color=_c(96, 56, 0),
        back_color=_c(0, 0, 0, 72),
        outline=3.0,
        shadow=1.4,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(192, 218, 230),
        secondary_color=_c(100, 180, 210),
        outline_color=_c(0, 58, 82),
        back_color=_c(0, 0, 0, 90),
        outline=2.1,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(236, 244, 250),
        secondary_color=_c(130, 200, 225),
        outline_color=_c(0, 60, 80),
        back_color=_c(0, 0, 0, 80),
        outline=2.2,
        shadow=0.9,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Bold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(218, 255, 220),
        secondary_color=_c(80, 242, 100),
        outline_color=_c(0, 78, 28),
        back_color=_c(0, 0, 0, 100),
        outline=2.1,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_CLEAN_EDITORIAL_STYLES: dict[str, KaraokeStyle] = {
    # The preset's language is "sung = the deeper tinted tone" (chorus gold,
    # bridge silver-blue, ad_lib sage). intro/verse/outro were the three
    # neutrals that had no tint at all — a 16..28 step of the same gray, which
    # left the sweep invisible. They now carry the same tints: cool blue for
    # the quiet sections, warm sand for the verse (a softer sibling of the
    # chorus gold, so it stays distinct from the blue bridge).
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Arial",
        fontsize=40,
        bold=False,
        italic=False,
        primary_color=_c(212, 216, 220),
        secondary_color=_c(118, 140, 164),
        outline_color=_c(28, 32, 36),
        back_color=_c(0, 0, 0, 82),
        outline=1.8,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Arial",
        fontsize=50,
        bold=True,
        italic=False,
        primary_color=_c(246, 246, 246),
        secondary_color=_c(196, 170, 116),
        outline_color=_c(30, 32, 34),
        back_color=_c(0, 0, 0, 72),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Arial",
        fontsize=54,
        bold=True,
        italic=False,
        primary_color=_c(250, 248, 244),
        secondary_color=_c(168, 152, 132),
        outline_color=_c(46, 40, 32),
        back_color=_c(0, 0, 0, 72),
        outline=2.2,
        shadow=1.1,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Arial",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 250),
        secondary_color=_c(232, 190, 90),
        outline_color=_c(70, 54, 18),
        back_color=_c(0, 0, 0, 70),
        outline=2.5,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Arial",
        fontsize=50,
        bold=True,
        italic=True,
        primary_color=_c(226, 232, 238),
        secondary_color=_c(166, 184, 206),
        outline_color=_c(38, 46, 56),
        back_color=_c(0, 0, 0, 76),
        outline=2.0,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Arial",
        fontsize=58,
        bold=True,
        italic=False,
        primary_color=_c(252, 246, 240),
        secondary_color=_c(188, 110, 80),
        outline_color=_c(74, 38, 26),
        back_color=_c(0, 0, 0, 70),
        outline=2.4,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Arial",
        fontsize=40,
        bold=False,
        italic=False,
        primary_color=_c(200, 202, 206),
        secondary_color=_c(112, 130, 152),
        outline_color=_c(28, 32, 36),
        back_color=_c(0, 0, 0, 84),
        outline=1.8,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Arial",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(238, 238, 240),
        secondary_color=_c(150, 158, 170),
        outline_color=_c(32, 36, 40),
        back_color=_c(0, 0, 0, 80),
        outline=1.9,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Arial",
        fontsize=36,
        bold=True,
        italic=True,
        primary_color=_c(226, 234, 226),
        secondary_color=_c(168, 202, 168),
        outline_color=_c(40, 58, 40),
        back_color=_c(0, 0, 0, 88),
        outline=1.8,
        shadow=0.8,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_CYBER_MINIMAL_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Semibold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(176, 226, 238),
        secondary_color=_c(0, 212, 232),
        outline_color=_c(0, 52, 66),
        back_color=_c(0, 0, 0, 80),
        outline=2.0,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Semibold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(232, 252, 255),
        secondary_color=_c(0, 238, 255),
        outline_color=_c(0, 58, 72),
        back_color=_c(0, 0, 0, 72),
        outline=2.4,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Semibold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(240, 250, 255),
        secondary_color=_c(110, 120, 255),
        outline_color=_c(18, 20, 80),
        back_color=_c(0, 0, 0, 70),
        outline=2.6,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Semibold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(255, 250, 255),
        secondary_color=_c(255, 64, 220),
        outline_color=_c(80, 0, 72),
        back_color=_c(0, 0, 0, 68),
        outline=2.8,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Semibold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(220, 230, 255),
        secondary_color=_c(130, 116, 255),
        outline_color=_c(30, 28, 84),
        back_color=_c(0, 0, 0, 74),
        outline=2.4,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Semibold",
        fontsize=60,
        bold=True,
        italic=False,
        primary_color=_c(255, 248, 240),
        secondary_color=_c(255, 168, 0),
        outline_color=_c(86, 54, 0),
        back_color=_c(0, 0, 0, 68),
        outline=2.8,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Semibold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(164, 206, 216),
        secondary_color=_c(0, 170, 196),
        outline_color=_c(0, 48, 62),
        back_color=_c(0, 0, 0, 82),
        outline=2.0,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Semibold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(234, 240, 244),
        secondary_color=_c(120, 196, 210),
        outline_color=_c(0, 52, 64),
        back_color=_c(0, 0, 0, 76),
        outline=2.2,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Semibold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(232, 255, 226),
        secondary_color=_c(88, 255, 150),
        outline_color=_c(0, 78, 46),
        back_color=_c(0, 0, 0, 88),
        outline=2.0,
        shadow=0.0,
        alignment=2,
        margin_v=42,
    ),
}

AEGISUB_STAGE_LIGHTS_STYLES: dict[str, KaraokeStyle] = {
    "intro": KaraokeStyle(
        name="Intro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(210, 226, 255),
        secondary_color=_c(104, 166, 255),
        outline_color=_c(8, 38, 96),
        back_color=_c(0, 0, 0, 90),
        outline=2.2,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "verse": KaraokeStyle(
        name="Verse",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=False,
        primary_color=_c(252, 252, 255),
        secondary_color=_c(88, 178, 255),
        outline_color=_c(8, 42, 98),
        back_color=_c(0, 0, 0, 80),
        outline=2.6,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "prechorus": KaraokeStyle(
        name="PreChorus",
        fontname="Segoe UI Bold",
        fontsize=56,
        bold=True,
        italic=False,
        primary_color=_c(232, 220, 255),
        secondary_color=_c(190, 94, 255),
        outline_color=_c(62, 16, 100),
        back_color=_c(0, 0, 0, 78),
        outline=2.8,
        shadow=1.3,
        alignment=2,
        margin_v=42,
    ),
    "chorus": KaraokeStyle(
        name="Chorus",
        fontname="Segoe UI Bold",
        fontsize=66,
        bold=True,
        italic=False,
        primary_color=_c(255, 255, 255),
        secondary_color=_c(255, 214, 70),
        outline_color=_c(98, 64, 0),
        back_color=_c(0, 0, 0, 72),
        outline=3.2,
        shadow=1.6,
        alignment=2,
        margin_v=42,
    ),
    "bridge": KaraokeStyle(
        name="Bridge",
        fontname="Segoe UI Bold",
        fontsize=52,
        bold=True,
        italic=True,
        primary_color=_c(255, 226, 250),
        secondary_color=_c(255, 94, 206),
        outline_color=_c(92, 12, 72),
        back_color=_c(0, 0, 0, 80),
        outline=2.6,
        shadow=1.2,
        alignment=2,
        margin_v=42,
    ),
    "drop": KaraokeStyle(
        name="Drop",
        fontname="Segoe UI Bold",
        fontsize=64,
        bold=True,
        italic=False,
        primary_color=_c(222, 248, 255),
        secondary_color=_c(0, 230, 255),
        outline_color=_c(0, 80, 110),
        back_color=_c(0, 0, 0, 76),
        outline=3.0,
        shadow=1.5,
        alignment=2,
        margin_v=42,
    ),
    "outro": KaraokeStyle(
        name="Outro",
        fontname="Segoe UI Bold",
        fontsize=42,
        bold=False,
        italic=False,
        primary_color=_c(200, 208, 230),
        secondary_color=_c(125, 132, 190),
        outline_color=_c(28, 34, 74),
        back_color=_c(0, 0, 0, 92),
        outline=2.2,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
    "rap": KaraokeStyle(
        name="Rap",
        fontname="Segoe UI Bold",
        fontsize=44,
        bold=False,
        italic=False,
        primary_color=_c(240, 244, 250),
        secondary_color=_c(140, 180, 220),
        outline_color=_c(8, 36, 84),
        back_color=_c(0, 0, 0, 80),
        outline=2.3,
        shadow=0.9,
        alignment=2,
        margin_v=42,
    ),
    "ad_lib": KaraokeStyle(
        name="AdLib",
        fontname="Segoe UI Bold",
        fontsize=38,
        bold=True,
        italic=True,
        primary_color=_c(226, 255, 230),
        secondary_color=_c(92, 255, 130),
        outline_color=_c(0, 72, 34),
        back_color=_c(0, 0, 0, 100),
        outline=2.2,
        shadow=1.0,
        alignment=2,
        margin_v=42,
    ),
}
# ── Modern presets ────────────────────────────────────────────────────────
# Two looks the section-coded palettes cannot express with colour alone.
#
# pill: BorderStyle 3 = opaque box. In libass the box is filled with
# OutlineColour and `outline` becomes its padding, so outline_color IS the box
# colour here, not a border. Shadow 0 keeps the edge clean.
# ponytail: BorderStyle 3 draws a hard RECTANGLE — the name is aspirational.
# Rounded corners need a \p1 vector drawing on a layer below the text, which
# also means measuring the line's width. Upgrade there only if the square
# corners actually bother someone.
#
# focus-pull: the whole line sits out of focus and each syllable sharpens on its
# own attack. It exists only because effects.py now anchors \t at the syllable's
# offset — with the old line-relative \t every word sharpened at once.
_LOUD_KEYS = ("chorus", "drop")


def _modern_variants(base: KaraokeStyle, *, loud_fontsize: int) -> dict[str, KaraokeStyle]:
    """One base, per-section name + a size bump on the hook. Nothing else."""
    return {
        key: replace(
            base,
            name=SECTION_CODED_STYLES[key].name,
            fontsize=(
                loud_fontsize if key in _LOUD_KEYS
                else base.fontsize - 8 if key == "ad_lib"
                else base.fontsize
            ),
            italic=key == "ad_lib",
        )
        for key in SECTION_CODED_STYLES
    }


_PILL_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Bold",
    fontsize=52,
    bold=True,
    italic=False,
    primary_color=_c(225, 225, 230),    # waiting: soft white on the box
    secondary_color=_c(214, 255, 60),   # sung: reels lime
    outline_color=_c(14, 14, 18),       # the box itself
    back_color=_c(0, 0, 0, 255),        # transparent: no shadow box
    outline=6.0,                        # box padding
    shadow=0.0,
    alignment=2,
    margin_v=64,
    border_style=3,
)

PILL_STYLES: dict[str, KaraokeStyle] = _modern_variants(_PILL_BASE, loud_fontsize=60)

_FOCUS_PULL_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Bold",
    fontsize=56,
    bold=True,
    italic=False,
    primary_color=_c(148, 148, 158),    # waiting: dimmed, and blurred by \blur3
    secondary_color=_c(255, 255, 255),  # sung: sharp white
    outline_color=_c(8, 8, 12),
    back_color=_c(0, 0, 0, 120),
    outline=1.8,                        # thin: \blur muddies a heavy border
    shadow=1.0,
    alignment=2,
    margin_v=52,
    highlight_effect="focus",
)

FOCUS_PULL_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _FOCUS_PULL_BASE, loud_fontsize=64
)

# bold-highlight: the short-form caption spec that measures best today — heavy
# sans, hot fill on the active word, a rim thick enough to survive any
# background, parked in the lower-middle third instead of on the frame edge.
# Its power is contrast, not motion, so it keeps the plain sweep.
# ponytail: the references call for Montserrat/Proxima Nova Bold; neither is
# installed here and libass substitutes silently, so this uses Segoe UI Black.
# Install the font and change one field if the heavier cut is wanted.
_BOLD_HIGHLIGHT_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Black",
    fontsize=58,
    bold=True,
    italic=False,
    primary_color=_c(255, 255, 255),   # waiting: pure white
    secondary_color=_c(255, 214, 0),   # sung: hot yellow
    outline_color=_c(0, 0, 0),         # the rim that does the readability work
    back_color=_c(0, 0, 0, 160),
    outline=4.5,
    shadow=0.0,
    alignment=2,
    margin_v=150,                      # lower-middle third, not the very bottom
)

BOLD_HIGHLIGHT_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _BOLD_HIGHLIGHT_BASE, loud_fontsize=66
)

# word-reveal: nothing on screen ahead of the voice. Lyric-video look — the
# singer cannot read ahead, which is why it is its own preset and not a default.
_WORD_REVEAL_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Black",
    fontsize=58,
    bold=True,
    italic=False,
    primary_color=_c(255, 255, 255),
    secondary_color=_c(120, 240, 255),  # sung: cold cyan against the white
    outline_color=_c(10, 12, 20),
    back_color=_c(0, 0, 0, 140),
    outline=3.0,
    shadow=1.0,
    alignment=2,
    margin_v=120,
    highlight_effect="reveal",
)

WORD_REVEAL_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _WORD_REVEAL_BASE, loud_fontsize=66
)

# word-pop: the "word pop" caption — clean face, solid colour, a bounce on each
# attack. The bounce is vertical only (see effects._pop), so it never reflows.
_WORD_POP_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Black",
    fontsize=56,
    bold=True,
    italic=False,
    primary_color=_c(240, 240, 245),
    secondary_color=_c(255, 106, 92),   # sung: coral
    outline_color=_c(16, 10, 14),
    back_color=_c(0, 0, 0, 150),
    outline=3.5,
    shadow=1.0,
    alignment=2,
    margin_v=130,
    highlight_effect="pop",
)

WORD_POP_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _WORD_POP_BASE, loud_fontsize=64
)

# ── Motion presets ────────────────────────────────────────────────────────
# The first three that could not exist before: their effects animate position,
# rotation or uniform scale, so s06 gives every syllable its own Dialogue and
# \pos placed from real font metrics. Same face and geometry as word-pop —
# only the fill colour and the effect change, so the motion is what you are
# comparing and not a second variable.

_FLY_IN_BASE = replace(
    _WORD_POP_BASE,
    secondary_color=_c(120, 220, 255),   # sung: ice blue
    highlight_effect="fly-in",
)
FLY_IN_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _FLY_IN_BASE, loud_fontsize=64
)

_SWING_BASE = replace(
    _WORD_POP_BASE,
    secondary_color=_c(255, 208, 92),    # sung: warm amber
    highlight_effect="swing",
)
SWING_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _SWING_BASE, loud_fontsize=64
)

_PUNCH_BASE = replace(
    _WORD_POP_BASE,
    secondary_color=_c(255, 92, 141),    # sung: hot pink
    highlight_effect="punch",
)
PUNCH_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _PUNCH_BASE, loud_fontsize=64
)

# typewriter: letters land one at a time. Narrative pacing, so a lighter cut and
# generous tracking; the amber fill reads as terminal text rather than caption.
_TYPEWRITER_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Semibold",
    fontsize=52,
    bold=False,
    italic=False,
    primary_color=_c(232, 228, 218),
    secondary_color=_c(255, 176, 59),   # sung: amber
    outline_color=_c(10, 8, 6),
    back_color=_c(0, 0, 0, 130),
    outline=2.6,
    shadow=1.0,
    alignment=2,
    margin_v=110,
    highlight_effect="typewriter",
)

TYPEWRITER_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _TYPEWRITER_BASE, loud_fontsize=58
)

# glitch: chromatic aberration on a single Dialogue line. The style's SHADOW is
# the offset colour copy (cyan) and the outline is the opposite rim (magenta),
# which is why shadow is opaque and unusually far out.
# ponytail: this is one-sided aberration — real two-sided needs a ghost Dialogue
# per line at an offset \pos, i.e. s06 emitting more than one event per line.
# Worth doing only if the single offset reads as too tame on real footage.
_GLITCH_BASE = KaraokeStyle(
    name="Verse",
    fontname="Segoe UI Black",
    fontsize=56,
    bold=True,
    italic=False,
    primary_color=_c(122, 134, 166),    # waiting: muted slate, so the sweep reads
    secondary_color=_c(255, 255, 255),
    outline_color=_c(255, 0, 110),      # magenta rim
    back_color=_c(0, 229, 255),         # cyan offset copy, fully opaque
    outline=2.0,
    shadow=4.0,
    alignment=2,
    margin_v=120,
)

GLITCH_STYLES: dict[str, KaraokeStyle] = _modern_variants(
    _GLITCH_BASE, loud_fontsize=64
)


# The syllable effect each style key sings with. Two values on purpose: the
# sweep for lyrics, an instant fill for ad-libs. The old table also carried a
# "color" name per style that no renderer ever read, and a "fade_in" that
# libass discarded (a line-scoped \fad already comes from the event itself,
# and the first one wins).
STYLE_EFFECTS: dict[str, str] = {
    "intro": "highlight",
    "verse": "highlight",
    "prechorus": "highlight",
    "chorus": "highlight",
    "bridge": "highlight",
    "drop": "highlight",
    "outro": "highlight",
    "rap": "highlight",
    "ad_lib": "none",
}

PRESET_LIBRARY: dict[str, StylePreset] = {
    "default": StylePreset(
        id="default",
        label="Default",
        version=1,
        description="Clean professional karaoke subtitles.",
        styles=DEFAULT_STYLES,
    ),
    "neon": StylePreset(
        id="neon",
        label="Neon",
        version=1,
        description="Original neon karaoke subtitles.",
        styles=NEON_STYLES,
    ),
    "cyberpunk": StylePreset(
        id="cyberpunk",
        label="Cyberpunk",
        version=1,
        description="Premium synthwave karaoke subtitles.",
        styles=CYBERPUNK_STYLES,
    ),
    "section-coded": StylePreset(
        id="section-coded",
        label="Section Coded",
        version=1,
        description="Color-coded styles for song sections.",
        styles=SECTION_CODED_STYLES,
    ),
    "single-style-kf": StylePreset(
        id="single-style-kf",
        label="Single Style KF",
        version=1,
        description="One consistent visual style for every lyric section.",
        styles=SINGLE_STYLE_KF_STYLES,
    ),
    "aegisub-classic-blue": StylePreset(
        id="aegisub-classic-blue",
        label="Aegisub Classic Blue",
        version=1,
        description="Classic fansub blue/cyan karaoke styling.",
        styles=AEGISUB_CLASSIC_BLUE_STYLES,
    ),
    "aegisub-gold-chorus": StylePreset(
        id="aegisub-gold-chorus",
        label="Aegisub Gold Chorus",
        version=1,
        description="Warm white verses with gold hook emphasis.",
        styles=AEGISUB_GOLD_CHORUS_STYLES,
    ),
    "aegisub-anime-pop": StylePreset(
        id="aegisub-anime-pop",
        label="Aegisub Anime Pop",
        version=1,
        description="Bright pink, cyan, and yellow anime karaoke styling.",
        styles=AEGISUB_ANIME_POP_STYLES,
    ),
    "aegisub-soft-pastel": StylePreset(
        id="aegisub-soft-pastel",
        label="Aegisub Soft Pastel",
        version=1,
        description="Low-contrast mint, lavender, and rose subtitle styling.",
        styles=AEGISUB_SOFT_PASTEL_STYLES,
    ),
    "aegisub-night-glow": StylePreset(
        id="aegisub-night-glow",
        label="Aegisub Night Glow",
        version=1,
        description="Cool white, blue, and purple glow-friendly styling.",
        styles=AEGISUB_NIGHT_GLOW_STYLES,
    ),
    "aegisub-impact-red": StylePreset(
        id="aegisub-impact-red",
        label="Aegisub Impact Red",
        version=1,
        description="High-impact white and red karaoke styling.",
        styles=AEGISUB_IMPACT_RED_STYLES,
    ),
    "aegisub-dual-vocal": StylePreset(
        id="aegisub-dual-vocal",
        label="Aegisub Dual Vocal",
        version=1,
        description="Lead vocal cyan with distinct ad-lib and bridge colors.",
        styles=AEGISUB_DUAL_VOCAL_STYLES,
    ),
    "aegisub-clean-editorial": StylePreset(
        id="aegisub-clean-editorial",
        label="Aegisub Clean Editorial",
        version=1,
        description="Restrained editorial white, silver, and subtle gold styling.",
        styles=AEGISUB_CLEAN_EDITORIAL_STYLES,
    ),
    "aegisub-cyber-minimal": StylePreset(
        id="aegisub-cyber-minimal",
        label="Aegisub Cyber Minimal",
        version=1,
        description="Minimal cyan and magenta styling with dark outlines.",
        styles=AEGISUB_CYBER_MINIMAL_STYLES,
    ),
    "aegisub-stage-lights": StylePreset(
        id="aegisub-stage-lights",
        label="Aegisub Stage Lights",
        version=1,
        description="White, blue, magenta, and gold stage-light palette.",
        styles=AEGISUB_STAGE_LIGHTS_STYLES,
    ),
    "pill": StylePreset(
        id="pill",
        label="Pill",
        version=1,
        description="Social-caption look: lyrics ride an opaque box, lime fill.",
        styles=PILL_STYLES,
    ),
    "focus-pull": StylePreset(
        id="focus-pull",
        label="Focus Pull",
        version=1,
        description="Blurred line that sharpens syllable by syllable on the attack.",
        styles=FOCUS_PULL_STYLES,
    ),
    "bold-highlight": StylePreset(
        id="bold-highlight",
        label="Bold Highlight",
        version=1,
        description="Heavy white caption with a hot yellow fill and a thick black rim.",
        styles=BOLD_HIGHLIGHT_STYLES,
    ),
    "word-reveal": StylePreset(
        id="word-reveal",
        label="Word Reveal",
        version=1,
        description="Nothing on screen ahead of the voice: each syllable fades in on its attack.",
        styles=WORD_REVEAL_STYLES,
    ),
    "word-pop": StylePreset(
        id="word-pop",
        label="Word Pop",
        version=1,
        description="Clean coral caption that bounces on every vocal attack.",
        styles=WORD_POP_STYLES,
    ),
    "typewriter": StylePreset(
        id="typewriter",
        label="Typewriter",
        version=1,
        description="Amber letters landing one character at a time.",
        styles=TYPEWRITER_STYLES,
    ),
    "glitch": StylePreset(
        id="glitch",
        label="Glitch",
        version=1,
        description="Chromatic aberration: magenta rim over an offset cyan copy.",
        styles=GLITCH_STYLES,
    ),
    "fly-in": StylePreset(
        id="fly-in",
        label="Fly In",
        version=1,
        description="Each syllable rises into place and fades up, landing on its attack.",
        styles=FLY_IN_STYLES,
    ),
    "swing": StylePreset(
        id="swing",
        label="Swing",
        version=1,
        description="Each syllable tips in off-angle and settles level on its attack.",
        styles=SWING_STYLES,
    ),
    "punch": StylePreset(
        id="punch",
        label="Punch",
        version=1,
        description="Uniform overshoot on every attack — the bounce word-pop could not do.",
        styles=PUNCH_STYLES,
    ),
}

PRESETS: dict[str, Mapping[str, KaraokeStyle]] = {
    preset.id: preset.styles for preset in PRESET_LIBRARY.values()
}

SECTION_TO_STYLE = {
    "intro": "intro",
    "introduction": "intro",
    "opening": "intro",
    "verse": "verse",
    "verse 1": "verse",
    "verse 2": "verse",
    "verse 3": "verse",
    "estrofe": "verse",
    "estrofa": "verse",
    "rap": "rap",
    "rap verse": "verse",
    "spoken": "verse",
    "spoken word": "verse",
    "pre-chorus": "prechorus",
    "pre chorus": "prechorus",
    "prechorus": "prechorus",
    "pre-chorus 2": "prechorus",
    "pre-hook": "prechorus",
    "lift": "prechorus",
    "build": "prechorus",
    "build-up": "prechorus",
    "buildup": "prechorus",
    "chorus": "chorus",
    "chorus 2": "chorus",
    "chorus 3": "chorus",
    "refrao": "chorus",
    "refrão": "chorus",
    "refrán": "chorus",
    "hook": "chorus",
    "hook 2": "chorus",
    "big chorus": "chorus",
    "final chorus": "chorus",
    "climax": "chorus",
    "drop": "drop",
    "drop 1": "drop",
    "drop 2": "drop",
    "bridge": "bridge",
    "ponte": "bridge",
    "breakdown": "bridge",
    "break": "bridge",
    "interlude": "bridge",
    "guitar solo": "bridge",
    "solo": "bridge",
    "instrumental": "bridge",
    "instrumental break": "bridge",
    "spoken bridge": "bridge",
    "dialogue": "bridge",
    "transition": "bridge",
    "middle 8": "bridge",
    "middle eight": "bridge",
    "outro": "outro",
    "outro chorus": "outro",
    "outro hook": "outro",
    "ending": "outro",
    "fade out": "outro",
    "fade-out": "outro",
    "coda": "outro",
}


SECTION_PREFIX_FALLBACK: dict[str, str] = {
    "verse": "verse",
    "chorus": "chorus",
    "refra": "chorus",
    "hook": "chorus",
    "drop": "drop",
    "bridge": "bridge",
    "pont": "bridge",
    "break": "bridge",
    "interlude": "bridge",
    "intro": "intro",
    "outro": "outro",
    "pre": "prechorus",
    "build": "prechorus",
}



def list_preset_ids() -> list[str]:
    return list(PRESET_LIBRARY.keys())


def get_preset(preset_id: str) -> StylePreset:
    try:
        return PRESET_LIBRARY[preset_id]
    except KeyError as exc:
        raise KeyError(f"Unknown karaoke style preset: {preset_id}") from exc




def list_preset_metadata() -> list[dict[str, object]]:
    return [
        {
            "id": preset.id,
            "label": preset.label,
            "version": preset.version,
            "description": preset.description,
            "styles": list(preset.styles.keys()),
            "effects": list(preset.effects),
        }
        for preset in PRESET_LIBRARY.values()
    ]


def supported_style_keys() -> set[str]:
    return set(STYLE_EFFECTS.keys())


def is_supported_style(style: object) -> bool:
    return isinstance(style, str) and style in supported_style_keys()


def is_supported_effect(effect: object) -> bool:
    return isinstance(effect, str) and effect in SUPPORTED_EFFECTS


def resolve_section(label: str) -> tuple[str, str]:
    """Raw section label -> (canonical label, style key).

    Exact match first, so an ordinal like "verse 2" survives as the canonical
    label instead of every verse collapsing to "verse" in the review UI; then
    the numeric strip, then a prefix fallback, then the default style.
    """
    normalized = str(label or "").strip().lower()
    if normalized in SECTION_TO_STYLE:
        return normalized, SECTION_TO_STYLE[normalized]

    stripped = re.sub(r"[\s\d\(\)]+$", "", normalized).strip()
    if stripped and stripped in SECTION_TO_STYLE:
        return stripped, SECTION_TO_STYLE[stripped]

    for prefix, style in SECTION_PREFIX_FALLBACK.items():
        if normalized.startswith(prefix):
            return normalized, style

    return normalized, DEFAULT_STYLE_KEY




def validate_preset(preset: StylePreset) -> list[str]:
    errors: list[str] = []
    if not preset.id:
        errors.append("Preset is missing id")
    if not preset.label:
        errors.append(f"Preset {preset.id} is missing label")
    if preset.version < 1:
        errors.append(f"Preset {preset.id} has invalid version: {preset.version}")
    if not preset.styles:
        errors.append(f"Preset {preset.id} has no styles")
    if DEFAULT_STYLE_KEY not in preset.styles:
        errors.append(f"Preset {preset.id} is missing default style: {DEFAULT_STYLE_KEY}")
    for style_key, style in preset.styles.items():
        if not isinstance(style, KaraokeStyle):
            errors.append(f"Preset {preset.id} style {style_key} is not a KaraokeStyle")
    for effect in preset.effects:
        if not is_supported_effect(effect):
            errors.append(f"Preset {preset.id} has unsupported effect: {effect}")
    return errors


def validate_all_presets() -> list[str]:
    errors: list[str] = []
    for preset in PRESET_LIBRARY.values():
        errors.extend(validate_preset(preset))
    return errors
