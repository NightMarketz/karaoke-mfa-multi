# ADR-004 — Style Library versionada

| Campo                   | Valor                                                         |
| ----------------------- | ------------------------------------------------------------- |
| Status                  | Aceito                                                        |
| Contexto                | UI, `s05` e `s06` precisam concordar sobre styles/effects.    |
| Decisão                 | `scripts/karaoke_styles/library.py` é fonte única de presets. |
| Consequências positivas | Evita hardcode divergente.                                    |
| Consequências negativas | Mudanças de estilo precisam versionamento.                    |
