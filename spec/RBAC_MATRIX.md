# Matriz RBAC (modelo lógico)

⚠️ **Não há autenticação nem sessão no MVP** — é uma ferramenta local single-user
e o ator é sempre `local-user` no código. Esta matriz é um **modelo lógico**:
descreve *quais responsabilidades* existem, para orientar a evolução e deixar
claro o que jamais deve ser burlado. Não implica login.

## Papéis

| Papel | Responsabilidade |
|---|---|
| **Operator** | Cria jobs, faz upload, acompanha progresso. |
| **Reviewer** | Revisa issues, aprova previews, aceita risco. |
| **Maintainer** | Config, re-roda validação, inspeciona eventos. |
| **Admin** | Deleta jobs, muda limites, manutenção. |
| **System** | Scripts/agentes internos do pipeline. |

## Regras (load-bearing)

| Ação | Quem pode |
|---|---|
| Aprovar review point / aplicar sugestão / aceitar risco / aprovar full preview | Reviewer, Maintainer, Admin |
| `retry-validate` | Maintainer, Admin, System |
| Deletar job parado | Admin |
| **Deletar job rodando** | **ninguém** (409) |
| **Burlar o export gate** | **ninguém** |
| Editar Style Library ou `pipeline.toml` | Maintainer, Admin |

As duas regras em negrito são invariantes da
[Constituição](PROJECT_CONSTITUTION.md) §5, não apenas política de papel — valem
mesmo sem auth.
