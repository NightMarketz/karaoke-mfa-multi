"""
router.py — Pure MFA model routing logic.
No subprocess, no file I/O.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, List


@dataclass
class ModelPlan:
    acoustic: str
    dictionary: str
    g2p: Optional[str]

    def is_complete(self) -> bool:
        """True when acoustic + dictionary are both set."""
        return bool(self.acoustic) and bool(self.dictionary)


def pick_models(
    lang: str,
    lang_config: Dict[str, dict],
    strict: bool = True,
) -> ModelPlan:
    """
    Resolve which MFA models to use for ``lang``.

    Args:
        lang:         ISO 639-1 language tag (e.g. "en", "pt")
        lang_config:  dict parsed from config/languages.json
        strict:       if True and lang unknown, raise KeyError;
                      if False, use heuristic fallback names

    Returns:
        ModelPlan with acoustic, dictionary, and optional g2p.
    """
    if lang in lang_config:
        entry = lang_config[lang]
        return ModelPlan(
            acoustic=entry["acoustic"],
            dictionary=entry["dictionary"],
            g2p=entry.get("g2p"),
        )

    if strict:
        known = sorted(lang_config.keys())
        raise KeyError(
            f"Language '{lang}' not in config. "
            f"Known languages: {known}. "
            "Add it to config/languages.json or use strict=False for fallback."
        )

    # Heuristic fallback
    return ModelPlan(
        acoustic=f"{lang}_mfa",
        dictionary=f"{lang}_cv_mfa",
        g2p=f"{lang}_cv_mfa",
    )


def fallback_plan(lang: str, romanization_mode: str = "none") -> ModelPlan:
    """
    Build a last-resort ModelPlan.
    For Japanese (ja), romanization_mode='romaji' signals that input
    lyrics should be pre-romanized before alignment.
    """
    return ModelPlan(
        acoustic=f"{lang}_mfa",
        dictionary=f"{lang}_cv_mfa",
        g2p=f"{lang}_cv_mfa" if romanization_mode != "romaji" else None,
    )


def validate_plan(plan: ModelPlan, available_models: List[str]) -> List[str]:
    """
    Return a list of missing model names (empty = all present).
    ``available_models`` is a flat list of model identifiers
    (e.g., from `mfa model list acoustic`).
    """
    needed = [plan.acoustic, plan.dictionary]
    if plan.g2p:
        needed.append(plan.g2p)
    return [m for m in needed if m not in available_models]
