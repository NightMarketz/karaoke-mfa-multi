# RBAC_MATRIX — Karaoke MFA Multi

No MVP local, não há autenticação real. Esta matriz serve como **modelo lógico de permissões** para organizar responsabilidades internas, UI futura ou modo multiusuário posterior.

## 9.1 Roles

| Role | Descrição |
|---|---|
| `Operator` | Cria jobs, envia arquivos e acompanha progresso. |
| `Reviewer` | Revisa issues, aprova previews e aceita riscos. |
| `Maintainer` | Ajusta config, reroda validação, inspeciona eventos. |
| `Admin` | Pode deletar jobs, alterar limites e executar manutenção. |
| `System` | Scripts/agentes internos do pipeline. |

## 9.2 Matriz

| Ação | Operator | Reviewer | Maintainer | Admin | System |
|---|---:|---:|---:|---:|---:|
| Criar job | ✅ | ❌ | ✅ | ✅ | ❌ |
| Enviar ZIP/stems | ✅ | ❌ | ✅ | ✅ | ❌ |
| Escolher preset | ✅ | ❌ | ✅ | ✅ | ❌ |
| Ver status do job | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ver eventos sanitizados | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ver eventos completos | ❌ | ❌ | ✅ | ✅ | ✅ |
| Rodar pipeline | ✅ | ❌ | ✅ | ✅ | ✅ |
| Retry de validação | ❌ | ❌ | ✅ | ✅ | ✅ |
| Abrir Review Wizard | ✅ | ✅ | ✅ | ✅ | ✅ |
| Aprovar review point | ❌ | ✅ | ✅ | ✅ | ❌ |
| Aplicar sugestão | ❌ | ✅ | ✅ | ✅ | ❌ |
| Aceitar risco | ❌ | ✅ | ✅ | ✅ | ❌ |
| Renderizar preview completo | ❌ | ✅ | ✅ | ✅ | ✅ |
| Aprovar preview completo | ❌ | ✅ | ✅ | ✅ | ❌ |
| Baixar ASS final | ✅ | ✅ | ✅ | ✅ | ❌ |
| Baixar MP4 final | ✅ | ✅ | ✅ | ✅ | ❌ |
| Bypassar export gate | ❌ | ❌ | ❌ | ❌ | ❌ |
| Deletar job parado | ❌ | ❌ | ❌ | ✅ | ❌ |
| Deletar job rodando | ❌ | ❌ | ❌ | ❌ | ❌ |
| Alterar Style Library | ❌ | ❌ | ✅ | ✅ | ❌ |
| Alterar `pipeline.toml` | ❌ | ❌ | ✅ | ✅ | ❌ |
