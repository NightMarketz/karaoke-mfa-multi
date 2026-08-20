r"""Karaoke lines -> ASS Dialogue events.

The render layer. It sits ABOVE both the style vocabulary
(scripts/karaoke_styles/) and the timing analysis (scripts/review_wizard/),
and the pipeline stage (s06_generate_ass.py) sits above it — which is exactly
why it is here and not inside karaoke_styles: that package imports
review_wizard in zero places today, and putting the emitter inside it would
drag the review pipeline into the one clean leaf package in the tree.

The one rule that governs the times in here: \k, \t and \move all run on the
DIALOGUE's clock, which starts one preroll before line["start"]. Measuring an
attack from the line instead throws every animation early by the preroll and
leaves a lead-in effect with nowhere to come from.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.review_wizard.highlight_velocity import build_word_highlight_segments
from scripts.review_wizard.timing_layers import (
    classify_line_timing,
    gap_should_be_absorbed,
)
from scripts.karaoke_styles.library import KaraokeStyle
from scripts.karaoke_styles.ass_compile import compile_layer, unsupported_props
from scripts.karaoke_styles.effects import (
    DEFAULT_EFFECT,
    EFFECTS,
    TextEffect,
    resolve_effect,
    syllable_ass,
)
from scripts.karaoke_styles.fonts import measure, resolve_font_path
from scripts.karaoke_styles.layout import place

# Preset pixel values (fontsize, outline, shadow, margin_v) are authored
# against this canvas height and scaled to whatever the render asks for.
DESIGN_HEIGHT = 720
# Side margin as a share of frame width, so a long line wraps before the edge
# instead of at the flat 20px the style line used to carry.
SIDE_MARGIN_RATIO = 0.05


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("{", "")
        .replace("}", "")
        .replace("\\", "")
        .replace("\n", " ")
        .strip()
    )


def _quantize_kf_durations_to_centiseconds(
    durations_ms: list[int],
    *,
    target_ms: int,
    gap_cs: int = 0,
) -> list[int]:
    if not durations_ms:
        return []
    target_cs = max(len(durations_ms), int(round(target_ms / 10.0)) - gap_cs)
    durations = [max(1, int(round(duration_ms / 10.0))) for duration_ms in durations_ms]
    residual = target_cs - sum(durations)
    durations[-1] += residual
    if durations[-1] < 1:
        deficit = 1 - durations[-1]
        durations[-1] = 1
        for index in range(len(durations) - 2, -1, -1):
            if deficit <= 0:
                break
            available = max(0, durations[index] - 1)
            take = min(available, deficit)
            durations[index] -= take
            deficit -= take
    return durations


def _build_karaoke_text(
    words: list[dict],
    line_start_ms: int,
    effect: str,
    style_effect: str = "highlight",
    line_style: str | None = None,
    *,
    layer_index: int = 0,
    frame: tuple[int, int] | None = None,
) -> str:
    r"""
    Build the \kf tagged text for one karaoke line.

    Format: {\kf<duration_cs>}word {\kf<duration_cs>}word2 ...
    duration = word end - word start in centiseconds.

    A leading \k0 consumes time before the first word starts
    (silence/intro gap within the line).
    """
    # Minimum word highlight duration: 80ms = 8 centiseconds.
    # CTC forced alignment compresses function words (I, a, the) to zero
    # duration. A floor of 80ms ensures the highlight is visible even on
    # the fastest syllables without distorting the timing of longer words.
    MIN_WORD_MS = 80

    word_segment_groups = []
    for word in words:
        segments = build_word_highlight_segments(word)
        if not segments:
            continue
        start_ms = int(min(float(segment["start"]) for segment in segments) * 1000)
        end_ms = int(max(float(segment["end"]) for segment in segments) * 1000)
        if end_ms - start_ms < MIN_WORD_MS:
            end_ms = start_ms + MIN_WORD_MS
        word_segment_groups.append((segments, start_ms, end_ms))

    # Karaoke time consumed so far in this line, in centiseconds. ASS times \t
    # from the Dialogue start, so this is what lets an effect animate on the
    # syllable's own attack instead of on the line's first frame.
    elapsed_cs = 0

    def append_segment(
        target: list[str],
        *,
        duration_cs: int,
        visible_segment: str,
        offset_cs: int,
    ) -> None:
        target.append(
            syllable_ass(
                effect,
                duration_cs,
                visible_segment,
                offset_ms=offset_cs * 10,
                style_effect=style_effect,
                layer_index=layer_index,
                frame=frame,
            )
        )

    timing = classify_line_timing({"style": line_style or "", "words": words})
    gap_policies = timing["inter_word_gaps"]

    visual_parts = []
    prev_end_ms = line_start_ms
    for index, (segments, start_ms, end_ms) in enumerate(word_segment_groups):
        next_start_ms = word_segment_groups[index + 1][1] if index + 1 < len(word_segment_groups) else None
        gap_policy = gap_policies[index] if index < len(gap_policies) else None
        should_absorb_gap = gap_policy is not None and gap_should_be_absorbed(gap_policy)
        visual_end_ms = max(end_ms, next_start_ms) if next_start_ms is not None and should_absorb_gap else end_ms

        # The inter-word gap rides with the word that follows it. As its own
        # part it picked up a space on each side from the join below and burned
        # as "the  tomb" — the tag carries no glyph, so the second space was
        # pure padding that widened with the pause.
        word_parts = []
        gap_cs = max(0, (start_ms - prev_end_ms) // 10)
        if gap_cs > 0:
            word_parts.append(f"{{\\k{gap_cs}}}")
            elapsed_cs += gap_cs

        segment_prev_end_ms = start_ms
        visible_segments = [segment for segment in segments if str(segment.get("text", ""))]
        segment_runs = []
        for segment_index, segment in enumerate(visible_segments):
            visible_segment = _escape_ass_text(str(segment["text"]))
            if not visible_segment:
                continue
            segment_start_ms = int(float(segment["start"]) * 1000)
            segment_end_ms = int(float(segment["end"]) * 1000)
            if segment_index == len(visible_segments) - 1:
                segment_end_ms = max(segment_end_ms, visual_end_ms)
            if segment_end_ms - segment_start_ms < MIN_WORD_MS:
                segment_end_ms = segment_start_ms + MIN_WORD_MS
            segment_gap_cs = max(0, (segment_start_ms - segment_prev_end_ms) // 10)
            segment_runs.append(
                {
                    "gap_cs": segment_gap_cs,
                    "duration_ms": max(1, segment_end_ms - segment_start_ms),
                    "visible_segment": visible_segment,
                }
            )
            segment_prev_end_ms = segment_end_ms
        duration_cs_values = _quantize_kf_durations_to_centiseconds(
            [run["duration_ms"] for run in segment_runs],
            target_ms=max(1, visual_end_ms - start_ms),
            gap_cs=sum(run["gap_cs"] for run in segment_runs),
        )
        for run, duration_cs in zip(segment_runs, duration_cs_values):
            if run["gap_cs"] > 0:
                word_parts.append(f"{{\\k{run['gap_cs']}}}")
                elapsed_cs += run["gap_cs"]
            append_segment(
                word_parts,
                duration_cs=duration_cs,
                visible_segment=run["visible_segment"],
                offset_cs=elapsed_cs,
            )
            elapsed_cs += duration_cs

        if word_parts:
            chunk = "".join(word_parts)
            if segment_runs or not visual_parts:
                visual_parts.append(chunk)
            else:
                # Timing-only chunk (word had no visible text): glue it to the
                # previous word so it never becomes a space-padded part.
                visual_parts[-1] += chunk
        prev_end_ms = visual_end_ms

    return " ".join(visual_parts).strip()


def _effect_capability_gaps(
    lines: list[dict],
    styles: dict[str, KaraokeStyle],
) -> dict[str, list[str]]:
    r"""Effect id -> properties the ASS compiler dropped, for every effect in use.

    Resolved through resolve_effect, not read off line["effect"]: a plain
    "highlight" line is upgraded to its preset's highlight_effect, so a preset
    asking for something undeliverable renders as a bare sweep on every line
    while line["effect"] still says "highlight". That is exactly the case this
    report exists to catch.
    """
    gaps: dict[str, list[str]] = {}
    for line in lines:
        style = styles.get(line.get("style", "verse")) or styles.get("verse")
        style_effect = style.highlight_effect if style is not None else DEFAULT_EFFECT
        name = resolve_effect(line.get("effect", DEFAULT_EFFECT), style_effect)
        chosen = EFFECTS[name]
        if isinstance(chosen, TextEffect):
            continue
        missing = unsupported_props(chosen, anchored=chosen.needs_layout)
        if missing:
            gaps[name] = sorted(missing)
    return gaps


def _build_layout_events(
    line: dict,
    style: KaraokeStyle,
    *,
    scale: float,
    play_res: tuple[int, int],
    fade_tag: str,
    start_ts: str,
    end_ts: str,
    start_ms: int,
    effect: str,
    layer_index: int = 0,
    layer_no: int = 0,
) -> list[str]:
    r"""One Dialogue per syllable, each positioned with \pos.

    Every event spans the whole line window, so each syllable holds its fill
    back with a leading \k of the time elapsed before its own attack. That
    leading \k is the same number compile_syllable() anchors \t on, which is
    what keeps motion and fill agreed.

    `start_ms` is the DIALOGUE's start, which is the line's start minus the
    preroll — not line["start"]. \k, \t and \move all run on the Dialogue's
    clock, so measuring attacks from the line instead throws every animation
    early by the preroll AND leaves a lead-in effect with nowhere to come from:
    resolve() clamps at 0, so the first syllable's fly-in collapsed to
    \move(x,y,x,y,0,0) — a syllable that does not move, on every line.

    Anchoring is \an2, bottom-centre. MarginV means "distance from the bottom
    of the frame to the bottom of the text", so with \an2 the y we compute IS
    that edge and a layout preset lands on exactly the baseline every other
    preset in the library uses.
    """
    width_px, height_px = play_res
    font_path = resolve_font_path(style.fontname, bold=style.bold, italic=style.italic)
    # The ASS Fontsize this line's Style row carries. measure() converts it to
    # a FreeType size itself -- see fonts.py; they are not the same number.
    ass_size = round(style.fontsize * scale)

    texts: list[str] = []
    widths: list[float] = []
    space_after: list[float] = []
    attacks: list[int] = []
    durations: list[int] = []

    space_px = measure(" ", font_path=font_path, size_px=ass_size)
    for word in line["words"]:
        segments = [s for s in build_word_highlight_segments(word) if str(s.get("text", ""))]
        for i, segment in enumerate(segments):
            text = _escape_ass_text(str(segment["text"]))
            if not text:
                continue
            texts.append(text)
            widths.append(measure(text, font_path=font_path, size_px=ass_size))
            space_after.append(space_px if i == len(segments) - 1 else 0.0)
            seg_start_ms = int(float(segment["start"]) * 1000)
            seg_end_ms = int(float(segment["end"]) * 1000)
            attacks.append(max(0, seg_start_ms - start_ms))
            durations.append(max(1, (seg_end_ms - seg_start_ms) // 10))

    if not texts:
        return []

    placed = place(
        texts,
        widths=widths,
        space_after=space_after,
        max_width=width_px * (1 - 2 * SIDE_MARGIN_RATIO),
        centre_x=width_px / 2,
        bottom_y=height_px - round(style.margin_v * scale),
        # Exactly the ASS Fontsize, which is what libass stacks rows by. Not a
        # coincidence and not a guess: a Fontsize IS ascender + descender (the
        # same fact fonts.py derives measure() from), so it already is the
        # face's natural line height. Measured against a libass-wrapped render
        # of the same text: libass 74px, and the 1.2x this replaced gave 89.
        line_height=ass_size,
    )

    # No DEFAULT_EFFECT fallback here, deliberately. layer_index was chosen
    # by the caller against THIS effect's layer list, so silently swapping in
    # a different effect would index the wrong list -- a wrong layer drawn, or
    # an IndexError far from the cause. build_line_events raises KeyError on an
    # unknown name and s06 resolves through resolve_effect first, which is
    # where a retired name like "fade_in" already becomes the sweep.
    chosen = EFFECTS[effect]
    layer = chosen.layers[layer_index]
    karaoke = "kf" if layer.role == "main" else "k"
    dx, dy = layer.offset
    events = []
    for spot, attack_ms, duration_cs in zip(placed, attacks, durations):
        # On this path the offset is free: the syllable already carries \pos,
        # so a ghost is the same event drawn a few pixels over.
        anchor = (spot.x + spot.width / 2 + dx, spot.y + dy)
        token = compile_layer(
            layer,
            text=spot.text,
            duration_cs=duration_cs,
            attack_ms=attack_ms,
            anchor=anchor,
            frame=(width_px, height_px),
            karaoke=karaoke,
        )
        # An effect that animates offset compiles to \move, which already
        # carries the destination. Emitting \pos as well leaves libass with two
        # positioning tags; it keeps the first and drops the other, so the
        # motion would silently vanish (or the placement would).
        placement = "" if "\\move(" in token else f"\\pos({anchor[0]:.1f},{anchor[1]:.1f})"
        lead_cs = attack_ms // 10
        lead = f"{{\\k{lead_cs}}}" if lead_cs > 0 else ""
        events.append(
            f"Dialogue: {layer_no},{start_ts},{end_ts},{style.name},,0,0,0,,"
            f"{fade_tag}{{\\an2{placement}}}{lead}{token}"
        )
    return events


def build_line_events(
    line: dict,
    style: KaraokeStyle,
    *,
    effect: str,
    style_effect: str,
    style_key: str,
    scale: float,
    play_res: tuple[int, int],
    margin_lr: int,
    fade_tag: str,
    start_ts: str,
    end_ts: str,
    start_ms: int,
    line_start_ms: int,
) -> list[str]:
    r"""Every Dialogue this line emits: one per layer, or one per (layer, syllable).

    A layer is one more Dialogue on the path that already exists, so layers are
    cheap on a non-layout preset (L x 52 on the reference job) and expensive on
    a layout one (L x 538). The ceiling of 4 is set by the worse case.

    `start_ms` is the DIALOGUE's start -- one preroll before line["start"] --
    because \k, \t and \move all run on that clock. `line_start_ms` is
    line["start"], which is what the non-layout builder measures word gaps
    against.
    """
    chosen = EFFECTS[effect]
    if isinstance(chosen, TextEffect):
        layers: tuple = (None,)
        numbers: tuple[int, ...] = (0,)
    else:
        layers, numbers = chosen.layers, chosen.layer_numbers

    events: list[str] = []
    for index, (layer, number) in enumerate(zip(layers, numbers)):
        if chosen.needs_layout:
            events += _build_layout_events(
                line, style,
                scale=scale, play_res=play_res, fade_tag=fade_tag,
                start_ts=start_ts, end_ts=end_ts, start_ms=start_ms,
                effect=effect, layer_index=index, layer_no=number,
            )
            continue
        text = _build_karaoke_text(
            line["words"], line_start_ms, effect,
            style_effect=style_effect, line_style=style_key,
            layer_index=index, frame=play_res,
        )
        dx, dy = layer.offset if layer is not None else (0.0, 0.0)
        if dx or dy:
            # Measured (T0 gate, scratch/probes/probe_margins.py): with
            # alignment 2 the text is centred between the event's OWN MarginL
            # and MarginR, so centre_x = W/2 + (L - R)/2, and MarginV is the
            # distance from the bottom of the frame. Both verified against a
            # \pos control that moved by exactly the amount it was handed.
            #
            # The clamp is not cosmetic: an event margin of 0 means "inherit
            # the style's", NOT zero, so a ghost whose dx reached the base
            # margin would silently halve its own displacement.
            ml = max(1, round(margin_lr + dx))
            mr = max(1, round(margin_lr - dx))
            mv = max(1, round(style.margin_v * scale - dy))
        else:
            # 0,0,0 = inherit the style row, byte for byte what every shipped
            # line has carried since before layers existed.
            ml = mr = mv = 0
        events.append(
            f"Dialogue: {number},{start_ts},{end_ts},{style.name},,"
            f"{ml},{mr},{mv},,{fade_tag}{text}"
        )
    return events


