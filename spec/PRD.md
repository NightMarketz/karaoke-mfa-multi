# PRD — Karaoke MFA Multi

## Produto

Aplicação **local em Flask** (single-user, sem SaaS, sem nuvem) que recebe
*stems* de música + a letra e produz um **MP4 de karaokê** com legenda ASS
embutida (queimada) e destaque progressivo por palavra via tags `\kf`
(compatível com Aegisub).

O diferencial é **precisão de sincronia**: a letra é a verdade e o alinhamento é
forçado contra o áudio vocal, com um **Review Wizard** que trava o export até a
qualidade ser aprovada.

## Entradas aceitas

- **ZIP estilo Suno** (`suno_zip`) com os stems, **ou**
- **Uploads separados**: `vocals` + `instrumental`.
- **Letra** em texto (`lyrics_text`) com marcações de seção `[Verse]`, `[Chorus]`, `[Bridge]`, `[Drop]`, etc.
- **Preset visual** (vem da Style Library — ver ADR-004).

No MVP a **letra é obrigatória**: o caminho feliz usa alinhamento forçado
(`s03b`), com Whisper (`s03`) apenas como fallback técnico quando não há
`lyrics.txt`.

## Escopo

### No MVP
- App Flask local; upload por ZIP ou stems separados.
- Alinhamento forçado com a letra como *ground truth*.
- Pipeline `s03b → s04 → s05 → s06 → s07 → s08`.
- ASS com `\kf` editável no Aegisub.
- Render MP4 (ffmpeg, legenda queimada).
- Review Wizard (issues, preview, export gate).
- Manifests de proveniência com SHA-256.
- Observabilidade (`status.json`, `events.jsonl`, `summary.json`).

### Fora do MVP
Autenticação real, billing, storage em nuvem, fila distribuída, editor visual
completo, marketplace de estilos, treino por feedback de usuário, colaboração
multiusuário.

## Usuários-alvo

| Perfil | Precisa de |
|---|---|
| Criador de música | Gerar karaokê a partir dos próprios stems, rápido e local. |
| Editor de vídeo/legenda | ASS editável no Aegisub para ajuste fino. |
| Usuário técnico local | Rodar tudo na própria máquina, sem SaaS. |
| Desenvolvedor do projeto | Reconstruir/evoluir sem quebrar contratos. |

## Métricas de sucesso

- Uma geração completa produz `output.ass` + `output.mp4` + manifests.
- O ASS abre no Aegisub com diálogos `\kf`.
- O export **bloqueia** quando manifest/hash/grafo de artefatos é inválido.
- Job inválido falha com mensagem clara em `status.json` + `events.jsonl`.
- Os *contract tests* passam antes de qualquer mudança visual.

## Requisitos funcionais (FR)

Destaques (numeração preservada da spec anterior; conferir sempre contra código):

- **FR-005** — normalizar stems para WAV PCM 16-bit / 44.1 kHz / estéreo.
- **FR-006** — usar alinhamento forçado quando `lyrics.txt` existe.
- **FR-016** — bloquear o download a menos que o export gate permita.
- **FR-018** — `retry-validate` só quando a falha ocorreu no estágio `validating`.
- **FR-019** — invalidar artefatos *downstream* ao re-rodar um estágio.
- **FR-020** — presets vêm da Style Library, nunca hardcoded na UI.

> Os invariantes que sustentam esses requisitos estão em
> [PROJECT_CONSTITUTION.md](PROJECT_CONSTITUTION.md). O detalhamento técnico
> (rotas, estágios, timeouts) está em [SDD.md](SDD.md).
