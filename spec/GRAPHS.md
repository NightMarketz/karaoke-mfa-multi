# GRAPHS — Karaoke MFA Multi

## 4.1 Contexto do sistema

```mermaid
flowchart LR
  User[Usuário local] --> UI[Flask UI]
  UI --> Upload[Upload Validator]
  UI --> Runner[Pipeline Runner]
  UI --> Review[Review Wizard]
  UI --> Gate[Export Gate]
  Runner --> JobDir[jobs/{job_id}]
  Review --> JobDir
  Gate --> JobDir
  Runner --> FFmpeg[ffmpeg]
  Runner --> Aligners[CTC/MMS + HubertFA]
  Runner --> Ollama[Ollama opcional]
  Runner --> StyleLib[Style Library]
  Gate --> MP4[output.mp4]
  Gate --> ASS[output.ass]
```

## 4.2 Pipeline principal

```mermaid
flowchart TD
  A[Upload ZIP ou stems] --> B[Validar inputs]
  B --> C[Materializar vocals.wav, instrumental.wav, lyrics.txt]
  C --> D{s03b disponível com lyrics.txt?}
  D -->|Sim| E[s03b Forced Alignment]
  D -->|Não| F[s03 Whisper fallback]
  E --> G[transcript.json]
  F --> G
  G --> H[s04 Align / HubertFA / fallback]
  H --> I[aligned.json]
  I --> J[s05 Analyze]
  J --> K[analysis.json]
  K --> L[s06 Generate ASS]
  L --> M[output.ass + manifest]
  M --> N[s07 Render MP4]
  N --> O[output.mp4 + manifest]
  O --> P[s08 Validate]
  P --> Q{Contratos passam?}
  Q -->|Sim| R[Review Wizard / Export Gate]
  Q -->|Não| S[failed]
  R --> T{Gate libera?}
  T -->|Sim| U[Download MP4/ASS]
  T -->|Não| V[Preview/correção/aprovação]
```

## 4.3 Artifact graph

```mermaid
flowchart TD
  Lyrics[lyrics.txt] --> Transcript[transcript.json]
  Vocals[vocals.wav] --> Transcript
  Transcript --> Aligned[aligned.json]
  Vocals --> Aligned
  Transcript --> Analysis[analysis.json]
  Aligned --> Analysis
  Analysis --> ASS[output.ass]
  Vocals --> ASS
  ASS --> ASSManifest[output.ass.manifest.json]
  Instrumental[instrumental.wav] --> MP4[output.mp4]
  ASS --> MP4
  ASSManifest --> MP4
  MP4 --> MP4Manifest[output.mp4.manifest.json]
  ASSManifest --> Validate[s08 validation]
  MP4Manifest --> Validate
  Validate --> Review[review_wizard.json]
  Review --> ExportGate[export gate]
```

## 4.4 Review Wizard

```mermaid
flowchart TD
  A[Open Review] --> B[Create review_wizard.json]
  B --> C[Import artifacts]
  C --> D[Text Review]
  D --> E[Alignment Processing]
  E --> F[Quality Review]
  F --> G{Issues?}
  G -->|Não| H[ready]
  G -->|Sim| I[Focused Issue Editor]
  I --> J{Risco aceito ou correção?}
  J -->|Correção| K[EditOperation]
  J -->|Risco aceito| L[Preview Required]
  K --> F
  L --> M[Critical snippets preview]
  M --> N{Ainda precisa full preview?}
  N -->|Sim| O[Full preview render]
  N -->|Não| P[Export readiness]
  O --> Q[Full preview approval]
  Q --> P
  P --> R{Artifact mudou?}
  R -->|Sim| S[artifact_changed bloqueia]
  R -->|Não| T[Export liberado]
```
