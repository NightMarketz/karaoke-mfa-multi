# TASK_SPEC_TEMPLATE

Use este template para qualquer tarefa de implementação.

---

# TASK: <nome curto>

## 1. Contexto
Explique por que esta tarefa existe e qual contrato ela protege.

## 2. Objetivo
Resultado esperado em uma frase.

## 3. Escopo

### Incluído
- ...

### Fora do escopo
- ...

## 4. Arquivos afetados
- `path/to/file.py`
- `tests/test_x.py`

## 5. Entradas

| Entrada | Origem | Obrigatória | Observações |
|---|---|---:|---|
|  |  |  |  |

## 6. Saídas

| Saída | Path | Contrato |
|---|---|---|
|  |  |  |

## 7. Contratos que não podem quebrar
- ...
- ...

## 8. Regras de erro

| Caso | Comportamento esperado |
|---|---|
|  |  |

## 9. Observabilidade

Eventos obrigatórios:
- `...`

Campos mínimos:

```json
{
  "job_id": "...",
  "timestamp": 0,
  "event": "...",
  "stage": "...",
  "level": "info|warning|error",
  "message": "...",
  "details": {}
}
```

## 10. Testes obrigatórios

* Unit:
  * ...
* Contract:
  * ...
* Integration:
  * ...

## 11. Critérios de aceite

* [ ] ...
* [ ] ...
* [ ] ...

## 12. Riscos

| Risco | Mitigação |
| ----- | --------- |
|       |           |

## 13. Definition of Done local

* [ ] Código implementado.
* [ ] Testes relevantes passam.
* [ ] Artefatos gerados seguem schema.
* [ ] Eventos registrados.
* [ ] Nenhum contrato downstream quebrado.
