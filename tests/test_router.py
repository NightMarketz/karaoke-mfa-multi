"""
tests/test_router.py

Unit tests for karaoke.router
Category: Unit (no subprocess, no file I/O)
"""
import pytest
from karaoke.router import pick_models, fallback_plan, validate_plan, ModelPlan


LANG_CONFIG = {
    "en": {"acoustic": "english_mfa", "dictionary": "english_us_mfa", "g2p": "english_us_mfa"},
    "pt": {"acoustic": "portuguese_mfa", "dictionary": "portuguese_cv_mfa", "g2p": "portuguese_cv_mfa"},
    "ja": {"acoustic": "japanese_mfa", "dictionary": "japanese_cv_mfa", "g2p": None},
    "fr": {"acoustic": "french_mfa", "dictionary": "french_cv_mfa", "g2p": "french_cv_mfa"},
}


# ── pick_models ───────────────────────────────────────────────────────────────

class TestPickModels:
    def test_known_lang_returns_correct_plan(self):
        plan = pick_models("en", LANG_CONFIG)
        assert plan.acoustic == "english_mfa"
        assert plan.dictionary == "english_us_mfa"
        assert plan.g2p == "english_us_mfa"

    def test_ja_has_no_g2p(self):
        plan = pick_models("ja", LANG_CONFIG)
        assert plan.g2p is None

    def test_unknown_lang_strict_raises(self):
        with pytest.raises(KeyError, match="'zz'"):
            pick_models("zz", LANG_CONFIG, strict=True)

    def test_unknown_lang_not_strict_returns_fallback(self):
        plan = pick_models("zz", LANG_CONFIG, strict=False)
        assert "zz" in plan.acoustic
        assert "zz" in plan.dictionary

    def test_error_message_includes_known_langs(self):
        with pytest.raises(KeyError) as exc_info:
            pick_models("xx", LANG_CONFIG, strict=True)
        msg = str(exc_info.value)
        assert "en" in msg
        assert "pt" in msg

    def test_all_configured_langs_resolve(self):
        for lang in LANG_CONFIG:
            plan = pick_models(lang, LANG_CONFIG)
            assert plan.is_complete(), f"Plan for '{lang}' is incomplete"


# ── fallback_plan ─────────────────────────────────────────────────────────────

class TestFallbackPlan:
    def test_default_has_g2p(self):
        plan = fallback_plan("de")
        assert plan.g2p is not None

    def test_romaji_mode_has_no_g2p(self):
        plan = fallback_plan("ja", romanization_mode="romaji")
        assert plan.g2p is None

    def test_lang_name_in_model_names(self):
        plan = fallback_plan("es")
        assert "es" in plan.acoustic


# ── validate_plan ─────────────────────────────────────────────────────────────

class TestValidatePlan:
    def _available(self):
        return [
            "english_mfa", "english_us_mfa",
            "portuguese_mfa", "portuguese_cv_mfa",
        ]

    def test_all_present_returns_empty_list(self):
        plan = pick_models("en", LANG_CONFIG)
        missing = validate_plan(plan, self._available())
        assert missing == []

    def test_missing_model_returned(self):
        plan = pick_models("fr", LANG_CONFIG)
        missing = validate_plan(plan, self._available())
        assert "french_mfa" in missing

    def test_ja_no_g2p_not_checked(self):
        """ja has no G2P — validate should not flag it as missing."""
        plan = pick_models("ja", LANG_CONFIG)
        available = ["japanese_mfa", "japanese_cv_mfa"]
        missing = validate_plan(plan, available)
        assert missing == []


# ── ModelPlan dataclass ───────────────────────────────────────────────────────

class TestModelPlan:
    def test_complete_when_both_set(self):
        plan = ModelPlan(acoustic="a", dictionary="d", g2p=None)
        assert plan.is_complete()

    def test_incomplete_when_acoustic_missing(self):
        plan = ModelPlan(acoustic="", dictionary="d", g2p=None)
        assert not plan.is_complete()

    def test_incomplete_when_dict_missing(self):
        plan = ModelPlan(acoustic="a", dictionary="", g2p=None)
        assert not plan.is_complete()
