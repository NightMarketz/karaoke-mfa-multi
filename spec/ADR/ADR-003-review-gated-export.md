# ADR-003 — Export travado por review

**Status:** Aceito

## Contexto
Timing automático pode produzir erro **perceptual** que passa em todos os testes
de contrato mas fica visivelmente errado no vídeo. Não dá para confiar cegamente.

## Decisão
O download final (`output.mp4`, `output.ass`) passa por um **export gate**. Só
libera quando o Review Wizard completou o fluxo exigido e os fingerprints do
preview aprovado ainda batem com os artefatos em disco.

## Consequências
- ✅ Erro perceptual é barrado por um humano antes do export.
- ✅ Rotas de export retornam **403** quando bloqueadas (`_blocked_final_export_reason`).
- ⚠️ Mudar o artefato depois de aprovado (hash muda) volta o estado para `quality_review`.

Ver [../SDD.md](../SDD.md) §6, [../STATE_MACHINES.md](../STATE_MACHINES.md).
