import unittest

from scripts.karaoke_styles.library import (
    DEFAULT_STYLE_KEY,
    SUPPORTED_EFFECTS,
    StylePreset,
    get_preset,
    list_preset_metadata,
    list_preset_ids,
    resolve_section,
    supported_style_keys,
    validate_all_presets,
    validate_preset,
)

NEW_AEGISUB_PRESET_IDS = [
    "aegisub-classic-blue",
    "aegisub-gold-chorus",
    "aegisub-anime-pop",
    "aegisub-soft-pastel",
    "aegisub-night-glow",
    "aegisub-impact-red",
    "aegisub-dual-vocal",
    "aegisub-clean-editorial",
    "aegisub-cyber-minimal",
    "aegisub-stage-lights",
]

# Modern presets: the box-caption look, and the blur focus pull that needs the
# per-syllable \t offset to exist at all.
MODERN_PRESET_IDS = [
    "pill",
    "focus-pull",
    "bold-highlight",
    "word-reveal",
    "word-pop",
    "typewriter",
    "glitch",
    "fly-in",
    "swing",
    "punch",
    # Layer presets: the four looks that could not exist before colour, layers
    # and a mask. Only "aberration" and "glow" cost extra events; "flare" is a
    # single main layer animating c, and "sweep" adds one over layer.
    "glow",
    "aberration",
    "flare",
    "sweep",
]

# The four presets built out of the layer/colour/mask vocabulary.
LAYER_PRESET_IDS = ["glow", "aberration", "flare", "sweep"]

# The presets whose effects libass cannot draw in place, so s06 emits one
# positioned Dialogue per syllable for them.
MOTION_PRESET_IDS = ["fly-in", "swing", "punch"]

# preset id -> the syllable effect its styles must select
MODERN_PRESET_EFFECT = {
    "pill": "highlight",
    "focus-pull": "focus",
    "bold-highlight": "highlight",
    "word-reveal": "reveal",
    "word-pop": "pop",
    "typewriter": "typewriter",
    "glitch": "highlight",
    "fly-in": "fly-in",
    "swing": "swing",
    "punch": "punch",
    "glow": "glow",
    "aberration": "aberration",
    "flare": "flare",
    "sweep": "sweep",
}


class KaraokeStyleLibraryTests(unittest.TestCase):
    def test_existing_preset_ids_are_available(self):
        self.assertEqual(
            [
                "default",
                "neon",
                "cyberpunk",
                "section-coded",
                "single-style-kf",
                *NEW_AEGISUB_PRESET_IDS,
                *MODERN_PRESET_IDS,
            ],
            list_preset_ids(),
        )

    def test_pill_preset_draws_an_opaque_box_behind_every_style(self):
        styles = get_preset("pill").styles
        self.assertEqual(supported_style_keys(), set(styles))   # count before verdict
        self.assertEqual({3}, {s.border_style for s in styles.values()})

    def test_focus_pull_preset_selects_the_focus_effect_everywhere(self):
        styles = get_preset("focus-pull").styles
        self.assertEqual(supported_style_keys(), set(styles))
        self.assertEqual({"focus"}, {s.highlight_effect for s in styles.values()})

    def test_each_modern_preset_selects_its_own_effect(self):
        self.assertEqual(sorted(MODERN_PRESET_IDS), sorted(MODERN_PRESET_EFFECT))
        for preset_id, effect in MODERN_PRESET_EFFECT.items():
            with self.subTest(preset=preset_id):
                styles = get_preset(preset_id).styles
                self.assertEqual(supported_style_keys(), set(styles))
                self.assertEqual({effect}, {s.highlight_effect for s in styles.values()})

    def test_motion_presets_ask_for_layout(self):
        from scripts.karaoke_styles.effects import EFFECTS

        self.assertEqual(3, len(MOTION_PRESET_IDS))
        for preset_id in MOTION_PRESET_IDS:
            with self.subTest(preset=preset_id):
                styles = get_preset(preset_id).styles
                self.assertEqual(supported_style_keys(), set(styles))
                effect = EFFECTS[preset_id]
                self.assertTrue(effect.needs_layout, f"{preset_id} does not move")

    def test_motion_presets_rest_in_a_neutral_pose(self):
        r"""A track's first key is what the syllable LOOKS like at rest.

        libass holds that static value from the Dialogue's first frame until
        the key's own time, which for a syllable late in the line is most of
        the time it is on screen. punch opening on scale 0.86 drew every unsung
        word narrower than the width we measured and placed it at, so the words
        visibly came apart -- "ilusão" rendered "i lu são". swing opening on
        -9 degrees left the whole unsung tail looking italic.

        The one exemption is an effect that also rests INVISIBLE: fly-in holds
        offset_y at +80 with alpha at 0, which is the point of a fly-in.
        """
        from scripts.karaoke_styles.effects import EFFECTS

        neutral = {"scale": 1.0, "scale_x": 1.0, "scale_y": 1.0,
                   "rotate": 0.0, "offset_x": 0.0, "offset_y": 0.0}
        checked = 0
        for preset_id in MOTION_PRESET_IDS:
            effect = EFFECTS[preset_id]
            alpha = next((t for t in effect.tracks if t.prop == "alpha"), None)
            hidden_at_rest = alpha is not None and alpha.keys[0][1] == 0.0
            for track in effect.tracks:
                if track.prop not in neutral:
                    continue
                checked += 1
                if hidden_at_rest:
                    continue
                with self.subTest(preset=preset_id, prop=track.prop):
                    self.assertEqual(
                        neutral[track.prop], track.keys[0][1],
                        f"{preset_id}.{track.prop} rests in its animated extreme",
                    )
        # Cardinality: zero tracks examined would make the loop vacuously true.
        self.assertEqual(3, checked)

    def test_no_other_preset_takes_the_layout_path(self):
        # The layout path is new and costs one Dialogue per syllable. Every
        # preset that was shipping before must keep the single-event path, or
        # this change is not the addition it claims to be.
        from scripts.karaoke_styles.effects import EFFECTS

        others = [p for p in MODERN_PRESET_EFFECT if p not in MOTION_PRESET_IDS]
        # 7 before the layer presets, 11 with them: all four stay off layout.
        self.assertEqual(11, len(others))
        for preset_id in others:
            with self.subTest(preset=preset_id):
                effect = EFFECTS[MODERN_PRESET_EFFECT[preset_id]]
                self.assertFalse(effect.needs_layout, preset_id)

    def test_glitch_preset_offsets_a_coloured_shadow_copy(self):
        # Chromatic aberration on one Dialogue line: the shadow IS the offset
        # colour copy, so it must be far enough out to read and fully opaque.
        styles = get_preset("glitch").styles
        self.assertEqual(supported_style_keys(), set(styles))
        self.assertTrue(all(s.shadow >= 3.0 for s in styles.values()))
        self.assertTrue(all(s.back_color.startswith("&H00") for s in styles.values()))

    def test_bold_highlight_preset_keeps_the_heavy_outline_contrast(self):
        # The researched best-performer is contrast, not motion: hot fill over a
        # near-black rim thick enough to survive any background.
        styles = get_preset("bold-highlight").styles
        self.assertEqual(supported_style_keys(), set(styles))
        self.assertEqual({"highlight"}, {s.highlight_effect for s in styles.values()})
        self.assertTrue(all(s.outline >= 4.0 for s in styles.values()))

    def test_every_modern_preset_covers_all_style_keys(self):
        # Cardinality guard: a preset missing a section key silently falls back
        # to "verse" at render time, which reads as "the preset did nothing".
        self.assertEqual(14, len(MODERN_PRESET_IDS))
        for preset_id in MODERN_PRESET_IDS:
            with self.subTest(preset=preset_id):
                self.assertEqual(supported_style_keys(), set(get_preset(preset_id).styles))

    def test_preset_metadata_is_ui_ready(self):
        metadata = list_preset_metadata()

        self.assertIn(
            {
                "id": "section-coded",
                "label": "Section Coded",
                "version": 1,
                "description": "Color-coded styles for song sections.",
                "styles": ["intro", "verse", "prechorus", "chorus", "bridge", "drop", "outro", "rap", "ad_lib"],
                "effects": list(SUPPORTED_EFFECTS),
            },
            metadata,
        )


    def test_all_presets_validate(self):
        self.assertEqual([], validate_all_presets())

    def test_new_aegisub_presets_validate_and_have_required_styles(self):
        self.assertEqual([], validate_all_presets())
        required_styles = {"verse", "chorus", "bridge", "intro", "outro", "ad_lib"}

        for preset_id in NEW_AEGISUB_PRESET_IDS:
            preset = get_preset(preset_id)
            self.assertTrue(required_styles.issubset(set(preset.styles.keys())), preset_id)
            self.assertEqual(1, preset.version)
            self.assertTrue(preset.label.startswith("Aegisub "), preset.label)


    def test_unknown_preset_raises_clear_error(self):
        with self.assertRaisesRegex(KeyError, "Unknown karaoke style preset: missing"):
            get_preset("missing")

    def test_one_map_serves_every_stage(self):
        # s03b and s05 import this map instead of keeping their own; before,
        # four copies disagreed on 11 labels and s05 knew only 15 of the 57.
        from scripts.karaoke_styles.library import SECTION_TO_STYLE
        from scripts.s03b_lyrics_align import SECTION_TO_STYLE as S03B
        from scripts.s05_analyze import SECTION_TO_STYLE as S05

        self.assertGreaterEqual(len(SECTION_TO_STYLE), 50)
        self.assertIs(SECTION_TO_STYLE, S03B)
        self.assertIs(SECTION_TO_STYLE, S05)
        # every style a label can resolve to must exist in every preset
        produced = set(SECTION_TO_STYLE.values())
        self.assertTrue(produced)
        for preset_id in list_preset_ids():
            missing = produced - set(get_preset(preset_id).styles)
            self.assertEqual(set(), missing, f"{preset_id} lacks {missing}")

    def test_section_resolution_preserves_existing_aliases(self):
        # A label the map knows keeps its own text as the canonical label, so
        # "chorus 3" stays distinguishable from "chorus" downstream.
        self.assertEqual(("chorus 3", "chorus"), resolve_section("chorus 3"))
        self.assertEqual(("pre-chorus", "prechorus"), resolve_section("pre-chorus"))
        self.assertEqual(("drop", "drop"), resolve_section("drop"))
        self.assertEqual(("guitar solo", "bridge"), resolve_section("guitar solo"))



    def test_unknown_section_falls_back_to_verse(self):
        self.assertEqual(("heavy wall of sound", DEFAULT_STYLE_KEY), resolve_section("heavy wall of sound"))

    def test_supported_style_keys_include_current_analysis_keys(self):
        self.assertEqual(
            {"intro", "verse", "prechorus", "chorus", "bridge", "drop", "outro",
             "rap", "ad_lib"},
            supported_style_keys(),
        )

    def test_effect_support_matches_stage06_builder(self):
        # What a line may ask for, and what effects.py can actually render.
        from scripts.karaoke_styles.effects import EFFECTS

        self.assertEqual(("highlight", "none"), SUPPORTED_EFFECTS)
        for effect in SUPPORTED_EFFECTS:
            self.assertIn(effect, EFFECTS)


class StyleLibraryEdgeCaseTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # is_supported_style
    # ------------------------------------------------------------------
    def test_is_supported_style_returns_false_for_none(self):
        from scripts.karaoke_styles.library import is_supported_style
        self.assertFalse(is_supported_style(None))

    def test_is_supported_style_returns_false_for_empty_string(self):
        from scripts.karaoke_styles.library import is_supported_style
        self.assertFalse(is_supported_style(""))

    def test_is_supported_style_returns_false_for_integer(self):
        from scripts.karaoke_styles.library import is_supported_style
        self.assertFalse(is_supported_style(42))

    def test_is_supported_style_returns_true_for_verse(self):
        from scripts.karaoke_styles.library import is_supported_style
        self.assertTrue(is_supported_style("verse"))

    def test_is_supported_style_returns_true_for_all_known_keys(self):
        from scripts.karaoke_styles.library import is_supported_style, supported_style_keys
        for key in supported_style_keys():
            self.assertTrue(is_supported_style(key), key)

    def test_is_supported_style_returns_false_for_unknown_key(self):
        from scripts.karaoke_styles.library import is_supported_style
        self.assertFalse(is_supported_style("unknown_section"))

    def test_is_supported_style_is_case_sensitive(self):
        from scripts.karaoke_styles.library import is_supported_style
        self.assertFalse(is_supported_style("Verse"))
        self.assertFalse(is_supported_style("CHORUS"))

    # ------------------------------------------------------------------
    # is_supported_effect
    # ------------------------------------------------------------------
    def test_is_supported_effect_returns_false_for_unsupported(self):
        from scripts.karaoke_styles.library import is_supported_effect
        self.assertFalse(is_supported_effect("glow"))
        self.assertFalse(is_supported_effect("pulse"))

    def test_is_supported_effect_returns_false_for_none(self):
        from scripts.karaoke_styles.library import is_supported_effect
        self.assertFalse(is_supported_effect(None))

    def test_is_supported_effect_returns_false_for_empty_string(self):
        from scripts.karaoke_styles.library import is_supported_effect
        self.assertFalse(is_supported_effect(""))

    def test_is_supported_effect_returns_true_for_all_defined_effects(self):
        from scripts.karaoke_styles.library import is_supported_effect, SUPPORTED_EFFECTS
        for effect in SUPPORTED_EFFECTS:
            self.assertTrue(is_supported_effect(effect), effect)

    def test_is_supported_effect_is_case_sensitive(self):
        from scripts.karaoke_styles.library import is_supported_effect
        self.assertFalse(is_supported_effect("Highlight"))
        self.assertFalse(is_supported_effect("NONE"))

    def test_section_coded_verse_sweep_is_visible(self):
        # The waiting/sung pair used to be 245,245,245 -> 255,255,255: same hue,
        # 4% apart in brightness, so the \kf fill was invisible on every verse
        # line (14 of 79 lines in jobs/202605290001).
        from scripts.karaoke_styles.library import get_preset

        def rgb(ass_color: str) -> tuple[int, int, int]:
            c = ass_color.lstrip("&H")
            return int(c[6:8], 16), int(c[4:6], 16), int(c[2:4], 16)

        style = get_preset("section-coded").styles["verse"]
        waiting, sung = rgb(style.primary_color), rgb(style.secondary_color)
        distance = max(abs(a - b) for a, b in zip(waiting, sung))

        self.assertGreaterEqual(distance, 32, f"waiting={waiting} sung={sung}")
        self.assertLess(sum(waiting), sum(sung), "sung fill must be the brighter state")

    def test_every_preset_style_has_a_visible_kf_sweep(self):
        # Waiting and sung must be perceptibly different colors or the \kf fill
        # renders as no change at all. Presets disagree on direction (some sing
        # brighter, clean-editorial and soft-pastel sing into a deeper tint), so
        # the floor is on distance, not on which side is lighter.
        from scripts.karaoke_styles.library import PRESET_LIBRARY

        def rgb(ass_color: str) -> tuple[int, int, int]:
            c = ass_color.lstrip("&H")
            return int(c[6:8], 16), int(c[4:6], 16), int(c[2:4], 16)

        checked = 0
        weak = []
        for preset_id, preset in PRESET_LIBRARY.items():
            for style_key, style in preset.styles.items():
                checked += 1
                waiting, sung = rgb(style.primary_color), rgb(style.secondary_color)
                distance = max(abs(a - b) for a, b in zip(waiting, sung))
                if distance < 32:
                    weak.append(f"{preset_id}/{style_key}: {waiting} -> {sung} (dist {distance})")

        # Cardinality first: a fence over an empty set is green for free.
        self.assertGreaterEqual(checked, 100, "style library shrank - check the fence still covers it")
        self.assertEqual([], weak, f"{len(weak)} of {checked} styles have an invisible sweep")

    # ------------------------------------------------------------------
    # _c() color helper
    # ------------------------------------------------------------------
    def test_color_helper_produces_correct_ass_format(self):
        from scripts.karaoke_styles.library import _c
        # Pure white fully opaque: R=255, G=255, B=255, A=0 -> &H00FFFFFF
        self.assertEqual("&H00FFFFFF", _c(255, 255, 255))

    def test_color_helper_pure_black(self):
        from scripts.karaoke_styles.library import _c
        self.assertEqual("&H00000000", _c(0, 0, 0))

    def test_color_helper_encodes_bgr_not_rgb(self):
        from scripts.karaoke_styles.library import _c
        # R=255, G=0, B=0 → BGR bytes: 00 00 FF -> &H0000FF00
        result = _c(255, 0, 0)
        self.assertEqual("&H000000FF", result)

    def test_color_helper_alpha_channel(self):
        from scripts.karaoke_styles.library import _c
        # alpha=128 → 0x80 in AA position
        result = _c(0, 0, 0, 128)
        self.assertTrue(result.startswith("&H80"), result)

    def test_color_helper_zero_alpha_is_fully_opaque(self):
        from scripts.karaoke_styles.library import _c
        result = _c(220, 220, 220, 0)
        self.assertTrue(result.startswith("&H00"), result)

    def test_color_helper_returns_string(self):
        from scripts.karaoke_styles.library import _c
        self.assertIsInstance(_c(100, 150, 200), str)

    # ------------------------------------------------------------------
    # resolve_section edge cases
    # ------------------------------------------------------------------
    def test_resolve_section_handles_none_like_empty(self):
        # resolve_section uses str(label or '') so None falls through
        from scripts.karaoke_styles.library import resolve_section, DEFAULT_STYLE_KEY
        _, style = resolve_section(None)
        self.assertEqual(DEFAULT_STYLE_KEY, style)

    def test_resolve_section_strips_trailing_numbers(self):
        # The strip is the second chance, for ordinals the map does not list.
        from scripts.karaoke_styles.library import SECTION_TO_STYLE, resolve_section
        self.assertNotIn("chorus 99", SECTION_TO_STYLE)
        self.assertEqual(("chorus", "chorus"), resolve_section("chorus 99"))
        self.assertEqual(("verse", "verse"), resolve_section("verse (7)"))

    def test_resolve_section_handles_purely_numeric_label(self):
        from scripts.karaoke_styles.library import resolve_section, DEFAULT_STYLE_KEY
        _, style = resolve_section("12345")
        self.assertEqual(DEFAULT_STYLE_KEY, style)

    # ------------------------------------------------------------------
    # validate_preset edge cases
    # ------------------------------------------------------------------
    def test_validate_preset_rejects_missing_default_style_key(self):
        from scripts.karaoke_styles.library import validate_preset, StylePreset, get_preset, DEFAULT_STYLE_KEY
        base = get_preset("default")
        styles_without_verse = {k: v for k, v in base.styles.items() if k != DEFAULT_STYLE_KEY}
        preset = StylePreset(
            id="no-verse",
            label="No Verse",
            version=1,
            description="Missing default style.",
            styles=styles_without_verse,
        )
        errors = validate_preset(preset)
        self.assertTrue(any(DEFAULT_STYLE_KEY in e for e in errors), errors)

    def test_validate_preset_rejects_version_zero(self):
        from scripts.karaoke_styles.library import validate_preset, StylePreset, get_preset
        base = get_preset("default")
        preset = StylePreset(
            id="bad-version",
            label="Bad Version",
            version=0,
            description="Zero version test.",
            styles=base.styles,
        )
        errors = validate_preset(preset)
        self.assertTrue(any("version" in e for e in errors), errors)


class LayerPresetTests(unittest.TestCase):
    def test_every_layer_preset_selects_its_own_effect_on_every_style(self):
        from scripts.karaoke_styles.effects import EFFECTS

        checked = 0
        for preset_id in LAYER_PRESET_IDS:
            styles = get_preset(preset_id).styles
            # Count before verdict: an empty styles dict would pass the loop.
            self.assertEqual(supported_style_keys(), set(styles))
            for key, style in styles.items():
                with self.subTest(preset=preset_id, style=key):
                    self.assertEqual(preset_id, style.highlight_effect)
                    self.assertIn(style.highlight_effect, EFFECTS)
                    checked += 1
        self.assertEqual(len(LAYER_PRESET_IDS) * len(supported_style_keys()), checked)

    def test_no_layer_preset_exceeds_the_measured_ceiling(self):
        from scripts.karaoke_styles.effects import EFFECTS
        from scripts.karaoke_styles.keyframes import MAX_LAYERS

        self.assertEqual(4, len(LAYER_PRESET_IDS))
        for preset_id in LAYER_PRESET_IDS:
            with self.subTest(preset=preset_id):
                self.assertLessEqual(len(EFFECTS[preset_id].layers), MAX_LAYERS)

    def test_only_aberration_and_glow_pay_for_extra_events(self):
        from scripts.karaoke_styles.effects import EFFECTS

        self.assertEqual(1, len(EFFECTS["flare"].layers))
        self.assertEqual(2, len(EFFECTS["sweep"].layers))
        self.assertEqual(2, len(EFFECTS["glow"].layers))
        self.assertEqual(3, len(EFFECTS["aberration"].layers))

    def test_no_layer_preset_needs_the_positioned_path(self):
        # The whole reason the T0 gate was run first: a ghost that forced
        # needs_layout would multiply these presets by ten events per line.
        from scripts.karaoke_styles.effects import EFFECTS

        for preset_id in LAYER_PRESET_IDS:
            with self.subTest(preset=preset_id):
                self.assertFalse(EFFECTS[preset_id].needs_layout)

    def test_flare_rests_in_a_neutral_pose(self):
        # A track's FIRST key is the resting pose, held from the Dialogue's
        # first frame. An effect opening on its animated extreme leaves the
        # whole unsung tail of the line sitting in that extreme -- measured on
        # burned frames when punch rested at 0.86 and swing at -9 degrees.
        from scripts.karaoke_styles.effects import EFFECTS

        tracks = EFFECTS["flare"].main.tracks
        self.assertEqual(2, len(tracks))          # count before verdict
        for track in tracks:
            with self.subTest(prop=track.prop):
                self.assertEqual(track.keys[0][1], track.keys[-1][1])


if __name__ == "__main__":
    unittest.main()
