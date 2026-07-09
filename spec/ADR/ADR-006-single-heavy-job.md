# ADR-006 — Um job pesado por vez no MVP

| Campo                   | Valor                                       |
| ----------------------- | ------------------------------------------- |
| Status                  | Aceito                                      |
| Contexto                | Pipeline usa CPU/GPU/ffmpeg intensivamente. |
| Decisão                 | `max_concurrent_jobs=1` por default.        |
| Consequências positivas | Evita saturar máquina local.                |
| Consequências negativas | Sem paralelismo inicial.                    |
