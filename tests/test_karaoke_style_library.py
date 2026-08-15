import unittest

from scripts.karaoke_styles.library import (
    DEFAULT_STYLE_KEY,
    LYRICS_SECTION_PREFIX_FALLBACK,
    LYRICS_SECTION_TO_STYLE,
    SUPPORTED_EFFECTS,
    StylePreset,
    get_animation_profile,
    get_preset,
    list_animation_profile_ids,
    list_animation_profile_metadata,
    list_preset_metadata,
    list_preset_ids,
    resolve_lyrics_section,
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
            ],
            list_preset_ids(),
        )

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
                "effect_profile": "clean_sweep",
            },
            metadata,
        )

    def test_animation_profile_ids_include_safe_and_future_profiles(self):
        self.assertEqual(
            [
                "clean_sweep",
                "instant",
                "outline_pop",
                "soft_glow",
                "bounce_word",
                "chorus_bloom",
                "syllable_float",
                "typewriter_clip",
                "aegisub_templater",
            ],
            list_animation_profile_ids(),
        )

    def test_safe_animation_profile_metadata_is_ui_ready(self):
        metadata = list_animation_profile_metadata()

        self.assertIn(
            {
                "id": "soft_glow",
                "label": "Soft Glow",
                "safety": "safe",
                "karaoke_tag": "kf",
                "line_effects": ["fade"],
                "word_effects": ["glow_pulse"],
                "layer_strategy": "single",
                "max_extra_layers": 0,
                "motion_intensity": "low",
                "description": "Readable sweep with a restrained outline glow pulse.",
            },
            metadata,
        )

    def test_preset_metadata_exposes_effect_profile(self):
        metadata_by_id = {item["id"]: item for item in list_preset_metadata()}

        self.assertEqual("clean_sweep", metadata_by_id["default"]["effect_profile"])
        self.assertEqual("soft_glow", metadata_by_id["neon"]["effect_profile"])
        self.assertEqual("outline_pop", metadata_by_id["cyberpunk"]["effect_profile"])

    def test_unknown_animation_profile_raises_clear_error(self):
        with self.assertRaisesRegex(KeyError, "Unknown karaoke animation profile: missing"):
            get_animation_profile("missing")

    def test_preset_validation_rejects_unknown_animation_profile(self):
        base = get_preset("default")
        preset = StylePreset(
            id="bad-profile",
            label="Bad Profile",
            version=1,
            description="Invalid profile test.",
            styles=base.styles,
            effect_profile_id="missing",
        )

        self.assertIn(
            "Preset bad-profile has unknown animation profile: missing",
            validate_preset(preset),
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

    def test_new_aegisub_preset_metadata_exposes_profiles(self):
        metadata_by_id = {item["id"]: item for item in list_preset_metadata()}

        expected_profiles = {
            "aegisub-classic-blue": "clean_sweep",
            "aegisub-gold-chorus": "soft_glow",
            "aegisub-anime-pop": "bounce_word",
            "aegisub-soft-pastel": "clean_sweep",
            "aegisub-night-glow": "soft_glow",
            "aegisub-impact-red": "outline_pop",
            "aegisub-dual-vocal": "clean_sweep",
            "aegisub-clean-editorial": "clean_sweep",
            "aegisub-cyber-minimal": "soft_glow",
            "aegisub-stage-lights": "bounce_word",
        }

        for preset_id, profile in expected_profiles.items():
            self.assertEqual(profile, metadata_by_id[preset_id]["effect_profile"])
            self.assertGreaterEqual(len(metadata_by_id[preset_id]["styles"]), 6)

    def test_unknown_preset_raises_clear_error(self):
        with self.assertRaisesRegex(KeyError, "Unknown karaoke style preset: missing"):
            get_preset("missing")

    def test_section_resolution_preserves_existing_aliases(self):
        self.assertEqual(("chorus", "chorus"), resolve_section("chorus 3"))
        self.assertEqual(("pre-chorus", "prechorus"), resolve_section("pre-chorus"))
        self.assertEqual(("drop", "drop"), resolve_section("drop"))
        self.assertEqual(("guitar solo", "bridge"), resolve_section("guitar solo"))

    def test_lyrics_section_resolution_preserves_stage03b_legacy_semantics(self):
        self.assertEqual(("chorus 3", "chorus"), resolve_lyrics_section("chorus 3"))
        self.assertEqual(("pre-chorus", "verse"), resolve_lyrics_section("pre-chorus"))
        self.assertEqual(("build", "verse"), resolve_lyrics_section("build"))
        self.assertEqual(("drop", "chorus"), resolve_lyrics_section("drop"))
        self.assertEqual(("drop", "chorus"), resolve_lyrics_section("drop 3"))
        self.assertEqual(("guitar solo", "bridge"), resolve_lyrics_section("guitar solo"))

    def test_lyrics_legacy_maps_are_available_for_stage03b_imports(self):
        self.assertEqual("verse", LYRICS_SECTION_PREFIX_FALLBACK["pre"])
        self.assertEqual("verse", LYRICS_SECTION_PREFIX_FALLBACK["build"])
        self.assertEqual("chorus", LYRICS_SECTION_PREFIX_FALLBACK["drop"])
        self.assertEqual("chorus", LYRICS_SECTION_TO_STYLE["drop"])

    def test_unknown_section_falls_back_to_verse(self):
        self.assertEqual(("heavy wall of sound", DEFAULT_STYLE_KEY), resolve_section("heavy wall of sound"))

    def test_supported_style_keys_include_current_analysis_keys(self):
        self.assertEqual(
            {"intro", "verse", "prechorus", "chorus", "bridge", "drop", "outro",
             "rap", "ad_lib"},
            supported_style_keys(),
        )

    def test_effect_support_matches_stage06_builder(self):
        for effect in ("highlight", "fade_in", "bounce", "flash", "none"):
            self.assertIn(effect, SUPPORTED_EFFECTS)


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
        from scripts.karaoke_styles.library import resolve_section
        self.assertEqual(("chorus", "chorus"), resolve_section("chorus 3"))
        self.assertEqual(("verse", "verse"), resolve_section("verse 2"))

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


if __name__ == "__main__":
    unittest.main()
