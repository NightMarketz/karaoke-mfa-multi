# DATA_DICTIONARY — Karaoke MFA Multi

## 10.1 `meta.json`

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---:|---|
| `job_id` | string | Sim | ID seguro do job. |
| `song_name` | string | Sim | Nome exibido na UI. |
| `preset` | string | Sim | Preset validado na Style Library. |
| `created_at` | number | Sim | Timestamp de criação. |
| `duration_s` | number | Recomendado | Duração do áudio. |
| `has_lyrics` | boolean | Sim | Deve ser `true` no MVP. |
| `source` | string | Sim | `zip`, `separate_stems` ou legado. |

## 10.2 `status.json`

| Campo | Tipo | Obrigatório | Valores |
|---|---|---:|---|
| `stage` | string | Sim | `queued`, `running`, `aligning_lyrics`, `transcribing`, `aligning`, `analyzing`, `generating`, `rendering`, `validating`, `done`, `failed` |
| `progress` | number | Sim | 0–100 |
| `error` | string | Sim | Vazio quando não há erro. |
| `updated_at` | number | Sim | Timestamp da última atualização. |
| `run_id` | string | Recomendado | ID da execução atual. |

## 10.3 `transcript.json`

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---:|---|
| `alignment_mode` | string | Sim | `forced` ou `whisper`. |
| `language` | string | Sim | Idioma. |
| `segments` | array | Sim | Segmentos alinhados. |
| `section_distribution` | object | Recomendado | Contagem por seção. |
| `unknown_section_markers` | array | Recomendado | Marcadores não reconhecidos. |

### `segments[]`

| Campo | Tipo | Obrigatório |
|---|---|---:|
| `text` | string | Sim |
| `section` | string | Recomendado |
| `start` | number | Sim |
| `end` | number | Sim |
| `words` | array | Sim |

### `segments[].words[]`

| Campo | Tipo | Obrigatório |
|---|---|---:|
| `word` | string | Sim |
| `start` | number | Sim |
| `end` | number | Sim |
| `probability` | number | Sim |

## 10.4 `aligned.json`

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---:|---|
| `words` | array | Sim | Palavras ordenadas com timing final. |

### `words[]`

| Campo | Tipo | Obrigatório |
|---|---|---:|
| `word` | string | Sim |
| `start` | number | Sim |
| `end` | number | Sim |
| `source` | string | Sim |
| `phonemes` | array | Não |

## 10.5 `analysis.json`

| Campo | Tipo | Obrigatório |
|---|---|---:|
| `lines` | array | Sim |

### `lines[]`

| Campo | Tipo | Obrigatório |
|---|---|---:|
| `text` | string | Sim |
| `start` | number | Sim |
| `end` | number | Sim |
| `style` | string | Sim |
| `color` | string | Recomendado |
| `effect` | string | Sim |
| `words` | array | Sim |

## 10.6 `output.ass.manifest.json`

| Campo | Tipo | Obrigatório |
|---|---|---:|
| `renderer_mode` | string | Sim |
| `style_preset_id` | string | Sim |
| `style_version` | number | Sim |
| `metrics` | object | Sim |
| `inputs` | object | Sim |
| `outputs` | object | Sim |

## 10.7 `review_wizard.json`

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---:|---|
| `project_id` | string | Sim | ID do projeto de revisão. |
| `job_id` | string | Sim | Job relacionado. |
| `schema_version` | number | Sim | Versão do schema. |
| `media_assets` | array | Sim | Assets importados. |
| `prepared_text` | object | Sim | Texto preparado. |
| `evidence_bundle` | object | Sim | Evidências de timing. |
| `alignment_takes` | array | Sim | Takes de alinhamento. |
| `edit_operations` | array | Sim | Operações manuais/auditáveis. |
| `issues` | array | Sim | Issues detectadas. |
| `quality_reports` | array | Sim | Relatórios de qualidade. |
| `preview_renders` | array | Sim | Previews gerados. |
| `approved_take_id` | string/null | Sim | Take aprovado. |
| `style_preset_id` | string | Sim | Preset usado. |
| `style_overrides` | object | Sim | Overrides locais. |
| `exports` | array | Sim | Exports aprovados. |
| `wizard_steps` | object | Sim | Estado da UI. |

## 10.8 Style Library

### Style keys suportadas

```txt
intro
verse
prechorus
chorus
bridge
drop
outro
ad_lib
```

### Effects suportados

```txt
highlight
fade_in
bounce
flash
none
```

### Presets mínimos

```txt
default
neon
cyberpunk
section-coded
single-style-kf
aegisub-classic-blue
aegisub-gold-chorus
aegisub-anime-pop
aegisub-soft-pastel
aegisub-night-glow
aegisub-impact-red
aegisub-dual-vocal
aegisub-clean-editorial
aegisub-cyber-minimal
aegisub-stage-lights
```
