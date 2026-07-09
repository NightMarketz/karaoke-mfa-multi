# ADR-001 — Arquitetura file-based

| Campo                   | Valor                                                                           |
| ----------------------- | ------------------------------------------------------------------------------- |
| Status                  | Aceito                                                                          |
| Contexto                | Jobs precisam ser debuggáveis, reproduzíveis e fáceis de inspecionar.           |
| Decisão                 | Cada job terá uma pasta própria em `jobs/{job_id}` como fonte da verdade.       |
| Consequências positivas | Debug simples, menor dependência de banco, fácil replay, fácil inspeção manual. |
| Consequências negativas | Requer disciplina de atomic write, locks e limpeza de artefatos.                |
