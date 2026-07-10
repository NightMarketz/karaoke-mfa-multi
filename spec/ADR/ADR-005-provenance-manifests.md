# ADR-005 — Manifests de proveniência (SHA-256)

**Status:** Aceito

## Contexto
É preciso provar **qual insumo produziu qual saída** — para o export gate confiar
que o MP4 servido corresponde ao ASS aprovado, e para detectar adulteração.

## Decisão
`output.ass` e `output.mp4` recebem manifests (`output.ass.manifest.json`,
`output.mp4.manifest.json`) com **sha256**, `size` e `created_at` de cada
input/output. O export gate compara os fingerprints aprovados com o disco; hash
divergente = bloqueio.

## Consequências
- ✅ Cadeia de proveniência `analysis → ass → mp4` verificável (`tests/test_validate_contracts.py`).
- ✅ `created_at` é automático e não é sobrescrito; hash é estável e sensível a conteúdo.
- ⚠️ Regerar um artefato invalida os manifests *downstream* (ver [../SDD.md](../SDD.md) §4).

Ver `tests/test_provenance_contracts.py`.
