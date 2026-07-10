# Dicionário de Dados

Schema de cada artefato do job. Cada linha "fixado por" aponta o *contract test*
que trava o formato — mude o schema e atualize o teste no mesmo commit.

O schema-mestre por estágio é `tests/test_pipeline_stage_contracts.py` (estilo
pytest — ver nota em [TEST_PLAN.md](TEST_PLAN.md)).

## `meta.json`
Metadados do job. `source ∈ {zip, separate_stems, legado}`, nome, preset,
timestamps.
**Fixado por:** `tests/test_common_contracts.py`.

## `status.json`
Estado atual: `stage`, `progress` (0–100), `updated_at` (obrigatório), mensagem.
Reflete o ponto do pipeline. **Fixado por:** `tests/test_common_contracts.py`,
`tests/test_validate_contracts.py`.

## `events.jsonl`
Append-only, um evento JSON por linha, com `job_id`. Eventos:
`stage_started`, `stage_command_finished`, `stage_failed`,
`downstream_invalidated`. Sumarizado em `summary.json` (timers por estágio,
registros de artefato, histórico de contagens de validação).
**Fixado por:** `tests/test_observability_contracts.py`.

## `transcript.json`
Saída de `s03`/`s03b`. `segments[]` → `words[]` com `start`, `end`,
`probability`. Campo **`alignment_mode ∈ {forced, whisper}`**. No caminho forçado
carrega rótulos de seção e metadados de *snap*.
**Fixado por:** `tests/test_pipeline_stage_contracts.py`, `tests/test_analysis_contract.py`.

## `aligned.json`
Saída de `s04`. `words[]` com `source` **obrigatório**; `phonemes` opcional.
**Fixado por:** `tests/test_pipeline_stage_contracts.py`.

## `analysis.json`
Saída de `s05`. `lines[]` exigem `text`, `start`, `end`, `style`, `effect`,
`words` (`color` recomendado). Timestamps monotônicos; fronteira da linha ==
primeira/última palavra; repetições de palavra preservadas por contagem.
- **Styles válidos:** `intro`, `verse`, `prechorus`, `chorus`, `bridge`, `drop`, `outro`, `ad_lib`.
- **Effects válidos:** `highlight`, `fade_in`, `bounce`, `flash`, `none`.
**Fixado por:** `tests/test_analysis_contract.py`, `tests/test_pipeline_stage_contracts.py`.

## `output.ass`
Saída de `s06`. Exige `[Script Info]`, `[V4+ Styles]`, `[Events]`, tags `\kf`,
≥1 `Dialogue`. Cor em BGR (roundtrip testado). `MIN_WORD_MS=80` como piso de
segmento. Estilos/efeitos vêm da Style Library ([ADR-004](ADR/ADR-004-versioned-style-library.md)).
**Fixado por:** `tests/test_s06_style_contracts.py`, `tests/test_ass_generation.py`.

## `output.ass.manifest.json`
Proveniência da geração ASS: `renderer_mode`, `style_preset_id`,
`style_version`, `metrics`, `inputs[]`, `outputs[]`, `run_id`, contagem de
*tail-trim*, diagnósticos de áudio, flags de pausa estrutural, diálogos por linha.
**Fixado por:** `tests/test_ass_generation.py`, `tests/test_provenance_contracts.py`.

## `output.mp4` / `output.mp4.manifest.json`
Vídeo final + manifest. Cada input/output tem **sha256**, `size`, `created_at`
(auto, não sobrescrito). Cadeia `analysis → ass → mp4` precisa bater no export.
**Fixado por:** `tests/test_provenance_contracts.py`, `tests/test_validate_contracts.py`.

## `review_wizard.json`
Projeto do Review Wizard. Hierarquia `line → word → syllable → melisma`;
segmentos de highlight-velocity por palavra; rastreabilidade de issue/quality/take.
**Fixado por:** `tests/test_review_wizard_contracts.py`.

## Presets da Style Library
15 presets reais em `scripts/karaoke_styles/library.py` (`PRESET_LIBRARY`):
`default`, `neon`, `cyberpunk`, `section-coded`, `single-style-kf`,
`aegisub-classic-blue`, `aegisub-gold-chorus`, `aegisub-anime-pop`,
`aegisub-soft-pastel`, `aegisub-night-glow`, `aegisub-impact-red`,
`aegisub-dual-vocal`, `aegisub-clean-editorial`, `aegisub-cyber-minimal`,
`aegisub-stage-lights`. Default: `single-style-kf`.
**Fixado por:** `tests/test_karaoke_style_library.py`.
