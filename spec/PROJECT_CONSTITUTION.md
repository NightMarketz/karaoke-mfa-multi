# PROJECT_CONSTITUTION — Karaoke MFA Multi

## 2.1 Princípios do projeto

### Princípio 1 — Arquivos são a fonte da verdade

Cada job vive em:

```txt
jobs/{job_id}/
```

A pasta contém inputs, outputs, estado, eventos, manifests e revisão. O sistema não deve depender de estado invisível em memória para reconstruir um job.

### Princípio 2 — Letra vence modelo no MVP

No caminho feliz do MVP, a letra enviada pelo usuário é o ground truth.
Whisper pode existir como fallback técnico, mas o fluxo principal usa:

```txt
lyrics.txt -> s03b_lyrics_align.py -> transcript.json
```

### Princípio 3 — Saída de modelo local é rascunho

Qualquer saída automática que afete timing, texto, render ou exportação deve passar por:

* validação de contrato;
* provenance;
* Review Wizard quando houver risco perceptual;
* export gate antes do download.

### Princípio 4 — Exportação final é privilégio, não default

`output.mp4` e `output.ass` só podem ser servidos quando:

* artefatos existem;
* manifests batem;
* hashes batem;
* quality report permite;
* preview necessário foi aprovado.

### Princípio 5 — Contratos primeiro, UI depois

A reescrita deve preservar os contratos antes de investir em cockpit bonito, timeline avançada ou edição visual.

### Princípio 6 — Não trocar silenciosamente decisões importantes

O sistema não pode:

* trocar preset desconhecido por default sem avisar;
* substituir timing manual por automático sem registrar operação;
* sobrescrever take agressivamente sem criar candidate take;
* ignorar hash divergente;
* exportar com artifact graph inválido.

## 2.2 Invariantes técnicos

| Invariante                 | Regra                              |
| -------------------------- | ---------------------------------- |
| `lyrics.txt`               | Obrigatório no MVP.                |
| `vocals.wav`               | Obrigatório para alinhamento.      |
| `instrumental.wav`         | Obrigatório para render.           |
| `transcript.json`          | Obrigatório antes de `s04`.        |
| `aligned.json`             | Obrigatório antes de `s05`.        |
| `analysis.json`            | Obrigatório antes de `s06`.        |
| `output.ass`               | Obrigatório antes de `s07`.        |
| `output.ass.manifest.json` | Obrigatório para render.           |
| `output.mp4.manifest.json` | Obrigatório para export.           |
| `status.json`              | Deve refletir estado atual do job. |
| `events.jsonl`             | Deve receber eventos append-only.  |

## 2.3 Valores de timing que não podem sumir

| Constraint                     | Valor default | Uso                                           |
| ------------------------------ | ------------: | --------------------------------------------- |
| `min_dur` de alinhamento       |         50 ms | Evita words zero-duration em `aligned.json`.  |
| `MIN_WORD_MS`                  |         80 ms | Garante highlight perceptível no ASS.         |
| `validation.min_duration`      |          1 ms | Erro duro em validação.                       |
| `validate_overlap_tolerance_s` |        0.05 s | Tolera overlaps pequenos.                     |
| `snap_window`                  |        0.75 s | Snap conservador em onset/pitch.              |
| `generate_ass_preroll_ms`      |        200 ms | Abre janela visual antes da primeira palavra. |
| `generate_ass_postroll_ms`     |        300 ms | Mantém linha depois da última palavra.        |
| `generate_ass_gap_ms`          |         50 ms | Gap mínimo entre linhas consecutivas.         |

## 2.4 Política de evidência de timing

| Evidência          | Política                                          |
| ------------------ | ------------------------------------------------- |
| Voz clara          | Vence beat.                                       |
| CTC                | Não cria melisma sozinho.                         |
| Pitch              | Não cria texto visível sozinho.                   |
| Edição manual      | Vence automático, mas precisa ser auditada.       |
| Conflito alto      | Vira issue.                                       |
| Correção agressiva | Gera candidate take, não substituição silenciosa. |

## 2.5 Regras proibidas

O projeto não deve permitir:

* Exportar MP4 com hash de ASS divergente.
* Criar job sem letra no MVP.
* Aceitar ZIP com path traversal.
* Emitir style/effect fora da Style Library.
* Perder repetições de palavras silenciosamente.
* Apagar artefatos downstream sem registrar rerun ou invalidation.
* Servir output final se o Review Wizard exigir preview.
* Tratar warning crítico como sucesso silencioso.
