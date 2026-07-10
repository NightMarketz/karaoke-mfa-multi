# Constituição do Projeto — Invariantes

Regras inegociáveis. Mudar qualquer valor aqui exige atualizar o teste que o
fixa (ver [TEST_PLAN.md](TEST_PLAN.md)) **antes** de mudar o código.

## 1. Princípios

1. **Job é um diretório.** `jobs/{job_id}` é a única fonte de verdade de um job; nada de estado invisível em memória (ver [ADR/ADR-001](ADR/ADR-001-file-based-architecture.md)).
2. **Letra é a verdade.** No MVP o alinhamento é forçado contra a letra; Whisper é fallback (ver [ADR/ADR-002](ADR/ADR-002-lyrics-first-mvp.md)).
3. **Saída automática é rascunho não confiável.** Qualquer saída automática que afete timing, texto, render ou export precisa passar por validação de contrato + proveniência + Review Wizard (quando há risco perceptual) + export gate. Isso vale inclusive para a análise via Ollama do `s05` — ela é rascunho, não verdade.

## 2. Contratos de artefato (ordenação obrigatória)

Cada estágio só roda se seu insumo existe:

| Antes de… | Precisa existir |
|---|---|
| `s04` (aligning) | `transcript.json` |
| `s05` (analyzing) | `aligned.json` |
| `s06` (generating) | `analysis.json` |
| `s07` (rendering) | `output.ass` + `output.ass.manifest.json` |
| export do MP4 | `output.mp4.manifest.json` |

Insumos obrigatórios: `lyrics.txt` (MVP), `vocals.wav` (alinhamento),
`instrumental.wav` (render). `status.json` reflete o estado atual;
`events.jsonl` é *append-only*. Schemas em [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

## 3. Valores de timing (load-bearing)

Fixados em código e no *snapshot* `tests/test_audio_alignment_contracts.py`.
Ao mudar qualquer valor, atualize esse teste no mesmo commit.

| Constante | Default | Onde (file:line) | Uso |
|---|---|---|---|
| `min_dur` (alinhamento) | **50 ms** (`0.050`) | `scripts/s03b_lyrics_align.py:485`, `scripts/s04_align.py:177` | Piso de duração de palavra; evita duração zero em `aligned.json`. |
| `MIN_WORD_MS` (display) | **80 ms** | `scripts/s06_generate_ass.py:456` | Piso do segmento `\kf` para o destaque ser perceptível. |
| `min_duration` (validação) | **1 ms** (`0.001`) | `scripts/common/validation.py:8` | Erro duro em `find_timestamp_errors` (s08). |
| overlap tolerance | **50 ms** (`0.05 s`) | `scripts/common/config.py:53`; `pipeline.toml [align].overlap_tolerance_s` | Sobreposição para trás tolerada antes de sinalizar. |
| `--snap-window` | **0.75 s** (default CLI) | `scripts/s03b_lyrics_align.py:1034` | Janela conservadora de *snap* de onset/pitch (`0` desliga). A assinatura da função tem default `1.5s`, mas o valor efetivo é o do CLI. |
| `preroll` | **200 ms** | `scripts/common/config.py:35` → `s06_generate_ass.py:662` | Janela abre antes da primeira palavra. |
| `postroll` | **300 ms** | `scripts/common/config.py:36` → `s06_generate_ass.py:663` | Janela fica após a última palavra. |
| `gap` | **50 ms** | `scripts/common/config.py:37` → `s06_generate_ass.py:670` | Gap mínimo entre linhas consecutivas no ASS. |

Correlatos (não no *snapshot* de timing, mas fixados): `low_confidence_threshold
= 0.25` e `lc_warning_pct = 20%` (`s03`), `vocal_activity.min_duration_s = 0.20`
(review wizard). `preroll/postroll/gap` são configuráveis via `pipeline.toml
[output]` ou env `KARAOKE_GENERATE_ASS_*_MS`.

## 4. Política de evidência de timing

- Batida de voz clara vence batida de métrica.
- CTC sozinho nunca **cria** melisma; pitch sozinho nunca cria texto visível.
- Edição manual vence o automático — mas precisa ser auditada.
- Conflito alto → vira **issue**. Correção agressiva → vira **candidate take**, nunca sobrescreve silenciosamente (ver [ADR/ADR-007](ADR/ADR-007-candidate-take.md)).

## 5. Ações proibidas

- Exportar MP4 com hash de ASS divergente do manifest.
- Criar job sem letra (no MVP).
- Aceitar *path traversal* em ZIP (ver `tests/test_safe_paths.py`).
- Emitir estilo/efeito fora da Style Library (ver [ADR/ADR-004](ADR/ADR-004-versioned-style-library.md)).
- Perder repetições de palavra silenciosamente.
- Apagar artefato *downstream* sem registrar rerun/invalidação.
- Servir output quando o Review Wizard exige preview.
- Tratar warning crítico como sucesso silencioso.

> Detalhes de rota, timeout e invalidação em [SDD.md](SDD.md). Papéis que podem
> ou não fazer cada ação em [RBAC_MATRIX.md](RBAC_MATRIX.md).
