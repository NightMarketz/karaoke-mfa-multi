# Backdrop procedural em lavfi — fatia A

## Título
`Trocar o canvas preto do s07 por um fundo procedural comandado por seção`

## Status
`rascunho`

## Objetivo
O MP4 deixa de ser letra sobre preto: o fundo é gerado em lavfi e muda de cor
conforme a seção da música, sem nenhum asset externo e sem novo estágio.

## Escopo

- **Dentro (fatia A):** `backdrop.cmd` escrito pelo s06; canvas do s07 trocado
  de `color=black` para `gradients → sendcmd → huesaturation`; whitelist de
  comando; fallback para preto; flag `--no-backdrop`; config em `[generate]`;
  três testes de contrato.
- **Fora (fatia B, mesmo arquivo):** envelope de áudio, glow
  (`colorlevels`+`gblur`+`blend`), 4 stems do Demucs, `geq`.
- **Fora (fatia C):** camadas nomeadas, presets de fundo, editor na UI,
  `openclsrc`.

A e B compartilham o mesmo artefato e o mesmo ponto de inserção. B adensa o
`.cmd` e estende o filtergraph; não refaz nada de A.

## Fonte de verdade / contratos que NÃO podem mudar

- Estágios `s01–s08` e seus nomes de artefato — nenhum estágio novo.
- `output.ass` e o contrato de `analysis.json` — inalterados. A fatia A **lê**
  `analysis.json`, não escreve nele.
- Valores de timing de [PROJECT_CONSTITUTION.md](../../spec/PROJECT_CONSTITUTION.md) §3 — não tocados.
- `supported_style_keys()` / `STYLE_DEFAULTS` em `scripts/karaoke_styles/library.py`
  seguem sendo a fonte única do eixo de estilo.
- Precedência de config CLI > env > `pipeline.toml` > default (skill `hardcoded-config-audit`).

## Tabela de evidência

Medido neste worktree, branch `claude/anime-compositing-satsuei-2585b3`,
ffmpeg 8.1-full (gyan), 1920x1080@30.

| ID | Arquivo | Item/Valor | Classificação | Risco | Decisão | Verificação |
|---|---|---|---|---|---|---|
| E001 | `scripts/s07_output.py:626` | `-i color=c=black:s=…` — canvas sintético | runtime | é o único ponto de inserção; errar aqui quebra todo render | trocar a string pela fonte procedural | `pytest tests/test_s07_backdrop.py` |
| E002 | `scripts/s07_output.py:636-648` | evento `stage07.canvas_selected`, `details.background="black"` | contrato/observabilidade | perder rastro de qual fundo foi usado | reusar o evento: `background`, `backdrop_sha256` | `pytest tests/test_s07_observability.py` |
| E003 | `scripts/karaoke_styles/library.py:1463` | `STYLE_DEFAULTS` — 9 styles → **5** cores distintas (`cool,default,intense,soft,warm`), cobertura 9/9 | contrato | criar um 6º mapa seção→X | **indexar a paleta pela cor (5), nunca pelo style (9)** | `pytest tests/test_backdrop_contract.py` |
| E004 | `docs/tasks/section-style-map-duplication.md` | 4 superfícies `SECTION_TO_STYLE`/`STYLE_DEFAULTS` já divergindo | contrato | virar a 5ª superfície | E003 evita por construção: a paleta pendura no eixo de cor existente | inspeção + E003 |
| E005 | `ffmpeg -h filter=gradients` | `c0`–`c7` **sem** flag `T`; só `speed` e `type` são comandáveis | runtime | desenhar em cima de suposição falsa | cor é comandada **depois** da fonte, em `huesaturation` | `ffmpeg -h filter=gradients` |
| E006 | probe `sec.mp4` | `sendcmd`→`huesaturation` muda croma por seção: 180 frames, soma das partes 180, UAVG 183.5/143.7/147.4, distintas | runtime | mecanismo não funcionar | mecanismo confirmado | probe reexecutável |
| E007 | probe | `geq` 1080p = **0,92×** realtime; `geq` 480×270 + `scale` = **8,65×** (150 frames cada) | runtime | render estourar o timeout | `geq` proibido em resolução plena (relevante só em B) | probe |
| E008 | probe | cadeia completa + `sendcmd`(300) + ASS + AAC + `h264_amf` = **1,62×**; 180 s → ~111 s vs `ffmpeg_timeout_s = 600` | runtime | timeout | folga ~5,4× (extrapolado de 5 s, não medido em 180 s) | probe |
| E009 | probe `itu.py` | cerca ITU: alvo `delta=0,45 cd/m²` OK; estrobo sabotado `delta=200,00` VIOLA (150 frames cada) | contrato | cerca verde vacuamente | cerca **já vista vermelha**; `assert` contra série vazia | `pytest tests/test_backdrop_itu.py` |
| E010 | `docs/tasks/section-style-map-duplication.md` | `tests/test_pipeline_stage_contracts.py` roda **0** testes sob `unittest` | fixture | reportar verde vacuo | verificação **só** por `pytest`, sempre com denominador | `pytest -q` (nunca `unittest`) |

## Passos

1. **Paleta.** Em `scripts/karaoke_styles/library.py`, `BACKDROP_PALETTE:
   dict[str, dict]` com **5 entradas**, chaveada pelos valores de `color` de
   `STYLE_DEFAULTS` (E003), mais `backdrop_for_color()`. Teste: toda cor
   produzida por `STYLE_DEFAULTS` tem entrada (5/5) e nenhuma sobra.
2. **Emissão.** `scripts/s06_generate_ass.py` passa a escrever
   `jobs/{id}/backdrop.cmd` junto de `output.ass`: uma linha por **troca de cor** entre
   linhas consecutivas de `analysis.json` (não por frame, não por linha), `t hue …; t saturation …; t intensity …`, timestamps
   monotônicos, derivados de `line["color"]` de `analysis.json`.
3. **Whitelist (fronteira de confiança).** Um único `_emit_command()` valida:
   filtro ∈ {`huesaturation`}, param ∈ {`hue`,`saturation`,`intensity`}, valor
   numérico dentro da faixa do filtro, timestamp monotônico ≥ 0. Nada do texto
   de `analysis.json` é interpolado cru — o rótulo só indexa a paleta.
4. **Consumo.** `scripts/s07_output.py`: a string do canvas vira
   `gradients=s=…:r=…:d=…:c0=…:c1=…:type=…:speed=…`, com `c0`/`c1`
   **fixos** vindos de `[generate]` (E005: não são comandáveis) — toda a
   variação por seção vem do `huesaturation` a jusante e o `vf_filter` ganha
   `sendcmd=f=<backdrop.cmd>,huesaturation` antes do `ass=`. Reusar
   `_build_subtitle_filter` para o escape de caminho no Windows.
5. **Fallback + flag.** `backdrop.cmd` ausente, vazio ou reprovado na whitelist
   → canvas preto, evento `stage07.backdrop_skipped` com o motivo, **render
   continua**. `--no-backdrop` força o caminho preto e mantém o smoke test
   `--no-subtitles` intacto.
6. **Config.** `[generate]`: `backdrop = true|false`, `backdrop_type`,
   `backdrop_speed`. Sem duplicar `resolution`/`framerate`, que já existem.

## Verificação executável

```bash
pytest tests/test_backdrop_contract.py tests/test_backdrop_itu.py tests/test_s07_backdrop.py -q
pytest tests/test_s07_observability.py tests/test_karaoke_style_library.py tests/test_s06_style_contracts.py -q
```

Os três testes novos:

- `test_backdrop_contract.py` — timestamps monotônicos; cobertura (nº de comandos emitidos ==
  nº de trocas de cor em `analysis.json`, +1 pela cor inicial); **negativo:** um
  `analysis.json` com rótulo hostil (`"chorus; drawtext=text=pwn"`) não pode
  produzir comando fora da whitelist.
- `test_backdrop_itu.py` — renderiza um job curto, mede `YAVG` por frame na
  faixa da letra, converte por BT.1702-3 Annex 2 (`V=(D−64)/876`, BT.1886, peak
  white 200 cd/m²), exige `delta < 20 cd/m²`; **controle negativo** com fixture
  de estrobo que precisa ficar vermelha; `assert` contra série vazia.
- `test_s07_backdrop.py` — o comando ffmpeg montado contém `gradients` e
  `sendcmd` quando há `backdrop.cmd`, e `color=c=black` quando não há ou quando
  `--no-backdrop`.

Toda contagem reportada com denominador. Nunca `unittest` (E010).

## Definition of Done
Cumpre [DEFINITION_OF_DONE.md](../../spec/DEFINITION_OF_DONE.md).
