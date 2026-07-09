# ADR-005 — Manifests com hashes SHA-256

| Campo                   | Valor                                                         |
| ----------------------- | ------------------------------------------------------------- |
| Status                  | Aceito                                                        |
| Contexto                | Render e export precisam provar qual input gerou qual output. |
| Decisão                 | `output.ass` e `output.mp4` terão manifests com hashes.       |
| Consequências positivas | Provenance forte e export gate confiável.                     |
| Consequências negativas | Mais arquivos e validações.                                   |
