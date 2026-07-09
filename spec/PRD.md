# PRD — Karaoke MFA Multi

## 1.1 Produto

**Karaoke MFA Multi** é uma ferramenta local para transformar **stems de música + letra** em um vídeo MP4 de karaoke sincronizado.

O produto aceita:

* ZIP de stems, por exemplo stems Suno.
* Upload separado de `vocals` e `instrumental`.
* Letra textual com seções como `[Verse]`, `[Chorus]`, `[Bridge]`, `[Drop]`.
* Preset visual de karaoke.
* Pipeline automático com revisão antes da exportação final.

## 1.2 Problema

Criar vídeos de karaoke sincronizados é trabalhoso porque envolve:

* Separação ou uso correto de stems.
* Alinhamento palavra a palavra.
* Preservação da letra real.
* Geração de legenda ASS compatível com Aegisub.
* Renderização final com áudio e legenda queimada.
* Revisão de erros perceptuais antes da exportação.

## 1.3 Objetivo do produto

Permitir que um usuário local gere um vídeo karaoke MP4 com:

* Letra sincronizada.
* Highlight por palavra usando `\kf`.
* Estilo visual controlado por presets.
* Artefatos debuggáveis.
* Exportação bloqueada se os contratos técnicos ou a revisão falharem.

## 1.4 Usuários-alvo

| Usuário                  | Necessidade                                             |
| ------------------------ | ------------------------------------------------------- |
| Criador musical          | Gerar vídeo karaoke a partir de stems próprios ou Suno. |
| Editor de vídeo/legenda  | Obter ASS compatível com Aegisub para ajuste fino.      |
| Usuário técnico local    | Rodar pipeline em máquina própria, sem SaaS.            |
| Desenvolvedor do projeto | Recriar ou evoluir o sistema sem quebrar contratos.     |

## 1.5 Escopo MVP

### Dentro do MVP

| Área            | Requisito                                                 |
| --------------- | --------------------------------------------------------- |
| Execução        | App local em Flask.                                       |
| Entrada         | ZIP de stems ou arquivos separados de vocal/instrumental. |
| Letra           | Obrigatória no MVP.                                       |
| Pipeline        | Etapas `s03b`, `s04`, `s05`, `s06`, `s07`, `s08`.         |
| Alinhamento     | Forced alignment com letra como ground truth.             |
| Legenda         | ASS com `\kf`, compatível com Aegisub.                    |
| Render          | MP4 final com áudio e legenda queimada.                   |
| Revisão         | Review Wizard com issues, preview e export gate.          |
| Provenance      | Manifests com hashes SHA-256.                             |
| Observabilidade | `status.json`, `events.jsonl`, summary e erros claros.    |

### Fora do MVP

| Item                                | Motivo                                        |
| ----------------------------------- | --------------------------------------------- |
| Autenticação real                   | Produto local, sem contas no MVP.             |
| Billing                             | Não é SaaS.                                   |
| Cloud storage                       | Jobs ficam em disco local.                    |
| Fila distribuída                    | Um job pesado por vez é suficiente no início. |
| Editor visual completo              | Começar com presets versionados.              |
| Marketplace de estilos              | Fora do valor principal.                      |
| Treinamento com feedback do usuário | Futuro.                                       |
| Colaboração multiusuário            | Futuro.                                       |

## 1.6 Métricas de sucesso

| Métrica             | Critério                                                                           |
| ------------------- | ---------------------------------------------------------------------------------- |
| Geração completa    | ZIP/stems + letra geram `output.ass`, `output.mp4` e manifests.                    |
| Compatibilidade ASS | Arquivo abre no Aegisub e contém diálogos com `\kf`.                               |
| Segurança de export | Export bloqueia se manifest, hash ou artifact graph estiver inválido.              |
| Robustez de erro    | Job inválido falha com mensagem clara em `status.json` e evento em `events.jsonl`. |
| Revisão             | Review Wizard cria projeto, issues, quality report e preview approval.             |
| Testabilidade       | Testes de contratos passam antes de mudanças visuais.                              |

## 1.7 User journeys

### Jornada A — Gerar karaoke com ZIP

1. Usuário acessa `/job/new`.
2. Envia ZIP com stems.
3. Cola letra.
4. Escolhe preset.
5. Sistema cria `jobs/{job_id}`.
6. Pipeline executa alinhamento, análise, ASS, render e validação.
7. Usuário abre Review Wizard.
8. Usuário aprova ou corrige issues.
9. Export gate libera MP4/ASS.
10. Usuário baixa `output.mp4`.

### Jornada B — Gerar karaoke com stems separados

1. Usuário envia `vocals.wav` e `instrumental.wav`.
2. Sistema valida formato e converte para WAV padrão.
3. Letra é usada como fonte de verdade.
4. Pipeline gera artefatos.
5. Review Wizard controla aprovação.
6. Export final é liberado somente se os contratos passarem.

### Jornada C — Job inválido

1. Usuário envia ZIP inseguro, sem vocal, sem instrumental ou sem letra.
2. Sistema rejeita antes de criar job pesado, ou falha em etapa validável.
3. `status.json` recebe `failed`.
4. `events.jsonl` registra causa.
5. UI mostra erro recuperável.

## 1.8 Requisitos funcionais

| ID     | Requisito                                                        |
| ------ | ---------------------------------------------------------------- |
| FR-001 | Criar job local a partir de ZIP de stems.                        |
| FR-002 | Criar job local a partir de vocals + instrumental.               |
| FR-003 | Exigir letra no MVP.                                             |
| FR-004 | Validar preset antes de criar job.                               |
| FR-005 | Normalizar stems para WAV PCM 16-bit, 44.1 kHz, stereo.          |
| FR-006 | Rodar forced alignment quando `lyrics.txt` existir.              |
| FR-007 | Gerar `transcript.json` com segmentos e palavras.               |
| FR-008 | Gerar `aligned.json` com palavras ordenadas e timestamps finais. |
| FR-009 | Gerar `analysis.json` com linhas, estilos e palavras.           |
| FR-010 | Gerar `output.ass` com seções obrigatórias e tags `\kf`.        |
| FR-011 | Gerar `output.ass.manifest.json`.                                |
| FR-012 | Renderizar `output.mp4` via ffmpeg.                              |
| FR-013 | Gerar `output.mp4.manifest.json`.                                |
| FR-014 | Validar contratos em `s08`.                                      |
| FR-015 | Criar Review Wizard sob demanda.                                 |
| FR-016 | Bloquear download se export gate não permitir.                   |
| FR-017 | Registrar eventos em `events.jsonl`.                             |
| FR-018 | Permitir retry de validação somente em falha de `validating`.    |
| FR-019 | Invalidar artefatos downstream ao rerodar etapas intermediárias. |
| FR-020 | Listar presets pela Style Library, não por hardcode na UI.       |

## 1.9 Requisitos não funcionais

| Categoria                | Requisito                                                    |
| ------------------------ | ------------------------------------------------------------ |
| Local-first              | O app deve funcionar sem SaaS obrigatório.                   |
| Auditabilidade           | Artefatos principais precisam ter manifests e hashes.        |
| Segurança                | Bloquear path traversal em ZIP e nomes de arquivo inseguros. |
| Confiabilidade           | Falhas precisam ser explícitas e rastreáveis.                |
| Debuggabilidade          | Cada etapa deve materializar artefatos intermediários.       |
| Compatibilidade          | ASS deve ser compatível com Aegisub.                         |
| Performance              | Pipeline deve respeitar timeouts configuráveis.              |
| Simplicidade operacional | Um job pesado por vez por padrão.                            |
| Reprodutibilidade        | Render deve validar input ASS antes de executar.             |
