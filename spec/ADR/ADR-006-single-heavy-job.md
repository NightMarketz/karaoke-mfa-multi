# ADR-006 — Um job pesado por vez

**Status:** Aceito

## Contexto
Demix, alinhamento e render saturam CPU/GPU/memória de uma máquina local. Rodar
vários jobs juntos trava a máquina e degrada todos.

## Decisão
`max_concurrent_jobs = 1` por default. `POST /job/new` retorna **429** quando o
número de threads vivas atinge o limite.

## Consequências
- ✅ Máquina local previsível; um job usa o hardware inteiro.
- ✅ Configurável via `pipeline.toml`/env para máquinas maiores (Maintainer/Admin).
- ⚠️ Fila é implícita (o usuário espera); não há fila distribuída (fora do MVP).

Ver [../SDD.md](../SDD.md) §6 e [../RBAC_MATRIX.md](../RBAC_MATRIX.md).
