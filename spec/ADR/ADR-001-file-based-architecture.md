# ADR-001 — Arquitetura baseada em arquivos

**Status:** Aceito

## Contexto
O pipeline tem estágios pesados e demorados (demix, alinhamento, render) que
podem falhar, ser retomados e auditados. Estado em memória se perde e é invisível.

## Decisão
Cada job é um diretório `jobs/{job_id}/` que é a **única fonte de verdade**.
Todos os artefatos (`input.wav`, `vocals.wav`, `transcript.json`, `aligned.json`,
`analysis.json`, `output.ass`, `output.mp4`, manifests), `meta.json`,
`status.json` e `events.jsonl` vivem nele. Nenhum estado de job relevante existe
só em memória.

## Consequências
- ✅ Retomável, inspecionável, testável por contrato de arquivo.
- ✅ `status.json`/`events.jsonl` dão observabilidade sem infra externa.
- ⚠️ Exige disciplina de escrita atômica, invalidação *downstream* explícita e limpeza (`CleanupAgent`).
- Guarda de segurança: `resolve_job_dir` rejeita id inseguro (path traversal).

Ver [../SDD.md](../SDD.md) §1 e §4.
