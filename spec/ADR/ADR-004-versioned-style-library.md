# ADR-004 — Style Library versionada

**Status:** Aceito

## Contexto
UI, `s05` (análise) e `s06` (geração ASS) precisam concordar sobre quais estilos,
cores e efeitos existem. Hardcode em cada camada diverge com o tempo.

## Decisão
`scripts/karaoke_styles/library.py` é a **única fonte** de presets, keys de
estilo e efeitos. `PRESET_LIBRARY` (library.py:1459) define os **15 presets**
reais: `default`, `neon`, `cyberpunk`, `section-coded`, `single-style-kf` e 10
`aegisub-*` (`classic-blue`, `gold-chorus`, `anime-pop`, `soft-pastel`,
`night-glow`, `impact-red`, `dual-vocal`, `clean-editorial`, `cyber-minimal`,
`stage-lights`). Default: `single-style-kf` (`pipeline.toml [ui]`).

## Consequências
- ✅ UI, `s05` e `s06` leem do mesmo lugar; nada de preset hardcoded na UI (FR-020).
- ✅ Keys de seção → estilo centralizadas (`SECTION_TO_STYLE`, `LYRICS_SECTION_TO_STYLE`).
- ⚠️ Novo estilo/efeito exige entrar na library, não na view.

Ver [../DATA_DICTIONARY.md](../DATA_DICTIONARY.md) (styles/effects) e `tests/test_karaoke_style_library.py`.
