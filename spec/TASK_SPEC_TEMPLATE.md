# Template de spec de tarefa

Molde para especificar uma fatia de trabalho antes de tocar no código (fluxo
SDD). Copie e preencha.

---

## Título
`<verbo no imperativo + escopo curto>`

## Status
`rascunho | aprovado | em execução | concluído`

## Objetivo
Uma frase: o que muda de verdade quando isto estiver pronto.

## Escopo
- **Dentro:** …
- **Fora:** …

## Fonte de verdade / contratos que NÃO podem mudar
Liste explicitamente (ids de estágio, nomes de artefato, thresholds, rotas) para
o escopo não vazar. Referencie [PROJECT_CONSTITUTION.md](PROJECT_CONSTITUTION.md)
e [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

## Tabela de evidência
Antes de editar, uma linha por decisão:

| ID | Arquivo | Item/Valor | Classificação | Risco | Decisão | Verificação |
|---|---|---|---|---|---|---|
| E001 | `scripts/…` | … | runtime/domínio/contrato/fixture/doc | o que quebra | o que fazer | comando que prova |

## Passos
1. …
2. …

## Verificação executável
Comando(s) que falham se o comportamento estiver errado:

```bash
pytest tests/test_<area>.py
# + para runtime/UI: python server.py e dirigir o fluxo
```

## Definition of Done
Cumpre [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md).
