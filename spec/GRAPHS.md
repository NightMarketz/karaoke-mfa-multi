# Grafos

Diagramas Mermaid. Verdade textual em [SDD.md](SDD.md) e
[STATE_MACHINES.md](STATE_MACHINES.md); aqui é a visão.

## Pipeline (fluxo de estágios e artefatos)

```mermaid
flowchart TD
    U[Upload: ZIP Suno ou vocals+instrumental + lyrics.txt] --> S01
    S01[s01_input\ninput.wav] --> S02[s02_demix\nvocals.wav + instrumental.wav]
    S02 --> B{lyrics.txt existe?}
    B -- sim --> S03B[s03b_lyrics_align\ntranscript.json forced]
    B -- nao --> S03[s03_transcribe\ntranscript.json whisper]
    S03B --> S04
    S03 --> S04[s04_align\naligned.json]
    S04 --> S05[s05_analyze\nanalysis.json]
    S05 --> S06[s06_generate_ass\noutput.ass + manifest]
    S06 --> S07[s07_output\noutput.mp4]
    S07 --> S08[s08_validate\ncontract tests + metricas]
    S08 --> D((done / failed))
```

## Ciclo de vida do job

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> aligning_lyrics: lyrics.txt existe
    queued --> transcribing: sem lyrics.txt
    aligning_lyrics --> aligning
    transcribing --> aligning
    aligning --> analyzing
    analyzing --> generating
    generating --> rendering
    rendering --> validating
    validating --> done
    validating --> failed
    failed --> validating: retry-validate (so se falhou em validating)
    done --> [*]
```

## Review Wizard

```mermaid
stateDiagram-v2
    [*] --> not_created
    not_created --> initialized
    initialized --> text_review
    text_review --> alignment_processing
    alignment_processing --> quality_review
    quality_review --> ready
    quality_review --> needs_fix
    needs_fix --> focused_issue_editor
    focused_issue_editor --> quality_review
    ready --> critical_snippets_approved
    critical_snippets_approved --> export_ready
    critical_snippets_approved --> full_preview_required
    full_preview_required --> full_preview_rendered
    full_preview_rendered --> full_preview_approved
    full_preview_approved --> export_ready
    export_ready --> exported
    export_ready --> quality_review: artifact_changed (hash/manifest muda)
```

## Export gate

```mermaid
flowchart TD
    R[GET output.mp4 / output.ass] --> A{artefatos presentes?}
    A -- nao --> BX1[403 blocked_missing_artifact]
    A -- sim --> M{manifest/hash bate?}
    M -- nao --> BX2[403 blocked_hash_mismatch]
    M -- sim --> Q{quality report ok?}
    Q -- nao --> BX3[403 blocked_quality_review_required]
    Q -- sim --> P{preview exigido e aprovado?}
    P -- nao --> BX4[403 blocked_preview_required]
    P -- sim --> OK[200 serve arquivo]
```
