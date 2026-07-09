# ADR-002 — Letra obrigatória no MVP

| Campo                   | Valor                                                       |
| ----------------------- | ----------------------------------------------------------- |
| Status                  | Aceito                                                      |
| Contexto                | Whisper pode divergir da letra real e quebrar karaoke.      |
| Decisão                 | MVP exige `lyrics.txt`; caminho feliz usa forced alignment. |
| Consequências positivas | Maior fidelidade textual e previsibilidade.                 |
| Consequências negativas | Usuário precisa fornecer letra.                             |
