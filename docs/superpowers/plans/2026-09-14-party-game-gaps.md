# Lacunas do jogo de festa — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar as lacunas #2 e #4 do `party.html`, preservar o WIP de take humano, e abrir a PR do refresh visual.

**Architecture:** Duas edições cirúrgicas em `web/party.html` (guarda `beforeunload` sobre o estado já existente; pontos no título da rodada). Um commit `wip:` em outro worktree pra parar de perder trabalho. Prova manual no browser com controle negativo, feita por quem NÃO implementou.

**Tech Stack:** HTML/JS vanilla (sem build), Flask (`server.py`), pytest.

Spec: `docs/superpowers/specs/2026-09-14-party-game-gaps-design.md`.

## Global Constraints

- Branch de trabalho: `claude/party-game-gaps-brainstorm-f33062`, neste worktree
  (`.claude/worktrees/gif-animation-resolution-upscale-b376d3`).
- Não tocar em nada além dos arquivos listados por tarefa. Nada de refatoração.
- `sed -i`/`perl -i` são vetados por hook; editar com a ferramenta Edit.
- Commits terminam com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Texto do diálogo `beforeunload` NÃO é customizável em browsers atuais — não tentar.
- Tarefas 1 e 2 são do executor (Sonnet). Tarefa 3 é do verificador (Opus) — o executor NÃO faz a Tarefa 3.
- Ao parar em lacuna (linha alvo divergente, status inesperado), reporte: o que está feito, a decisão pendente, as opções. Não escolha.

---

### Task 1: `beforeunload` + pontos no título em `party.html`

**Files:**
- Modify: `web/party.html:85` (comentário do bloco de estado)
- Modify: `web/party.html:94` (inserir logo após `let pontosDaRodada`)
- Modify: `web/party.html:186-187` (título em `proximoJogadorDaRodada`)

**Interfaces:**
- Consumes: `rodadaAtual` (0 no setup, 1..numRodadas durante o jogo, numRodadas+1 na tela final — `proximaRodada` incrementa antes de chamar `mostraFinal`), `numRodadas`, `jogadores[i].pontos` (acumulado entre rodadas, zerado em `iniciaPartida`).
- Produces: nada consumido por outra tarefa.

- [ ] **Step 1: Confirmar o estado das linhas alvo**

Run: `grep -nE "Estado, so em memoria|^let pontosDaRodada|vez de \\$\\{j.nome\\}" web/party.html`
Expected (3 linhas):
```
85:// ── Estado, so em memoria da aba: recarregar a pagina perde a partida ──────
94:let pontosDaRodada = []; // [{nome, pontos}] acumulado pra tela de resumo
187:    `Rodada ${rodadaAtual}/${numRodadas} — clipe "${clipeAtual.label}" — vez de ${j.nome}`;
```
Se qualquer linha divergir, PARE e reporte — não adapte.

- [ ] **Step 2: Trocar o comentário da linha 85**

De:
```js
// ── Estado, so em memoria da aba: recarregar a pagina perde a partida ──────
```
Para:
```js
// ── Estado, so em memoria da aba: recarregar a pagina perde a partida; a
// guarda beforeunload abaixo so evita o acidente, nao recupera nada ──────
```

- [ ] **Step 3: Inserir a guarda logo após a linha `let pontosDaRodada = ...`**

Inserir, com uma linha em branco antes e depois:
```js
// ponytail: guarda so pra notebook (decisao 2026-09-14). iOS nao dispara
// beforeunload — se o jogo for pra celular, trocar por sessionStorage.
window.addEventListener("beforeunload", (e) => {
  // rodadaAtual passa de numRodadas antes de mostraFinal: esse intervalo e
  // exatamente "partida em andamento".
  if (rodadaAtual > 0 && rodadaAtual <= numRodadas) e.preventDefault();
});
```

- [ ] **Step 4: Pontos no título**

Na linha do título (era a 187, agora deslocada), trocar:
```js
    `Rodada ${rodadaAtual}/${numRodadas} — clipe "${clipeAtual.label}" — vez de ${j.nome}`;
```
por:
```js
    `Rodada ${rodadaAtual}/${numRodadas} — clipe "${clipeAtual.label}" — vez de ${j.nome} (${j.pontos} pts)`;
```

- [ ] **Step 5: Checagem sintática do JS inline**

`party.html` não tem teste JS. Extrair o script e checar sintaxe (Bash):
```bash
python -c "
import re
s=open('web/party.html',encoding='utf-8').read()
js=re.findall(r'<script>(.*?)</script>',s,re.S)
assert len(js)>=1, 'nenhum <script> inline'
open('party_inline_check.js','w',encoding='utf-8').write('\n'.join(js))
" && node --check party_inline_check.js && echo SYNTAX_OK; rm -f party_inline_check.js
```
Expected: `SYNTAX_OK`. Se `node` não existir no PATH, reporte e siga — a Tarefa 3 cobre no browser.

- [ ] **Step 6: Conferir o diff**

Run: `git status --short && git diff --stat web/party.html`
Expected: status mostra **só** ` M web/party.html`; stat na casa de `+11 -2`.

- [ ] **Step 7: Commit**

```bash
git add web/party.html
git commit -m "feat(party): guarda beforeunload na partida em andamento; pontos acumulados no titulo da rodada

Lacunas #2 e #4 de docs/superpowers/specs/2026-09-14-party-game-gaps-design.md.
Notebook-only por decisao: iOS nao dispara beforeunload, celular pede sessionStorage.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Preservar o WIP de take humano (outro worktree, outra branch)

Worktree: `C:/Users/Katz/OneDrive/Desktop/Meus projetos/karaoke-mfa-multi/.claude/worktrees/sound-library-party-game-033efd` (branch `claude/sound-library-party-game-033efd`). Abaixo, `$W` significa esse caminho — use `git -C "$W"` com o caminho literal, não `cd`.

**Files (todos em `$W`):**
- Modificados: `server_score_addendum.py`, `tests/test_score_route.py`, `web/mimic.html`
- Novos: `docs/human-takes-protocol.md`, `scripts/analyze_human_takes.py`, `tests/test_analyze_human_takes.py`
- **NÃO adicionar:** `.claude/`

**Interfaces:** nenhuma — só commit de preservação. Não editar nenhum arquivo.

- [ ] **Step 1: Confirmar o estado esperado**

Run: `git -C "$W" status --short`
Expected exatamente estas 7 linhas (ordem pode variar):
```
 M server_score_addendum.py
 M tests/test_score_route.py
 M web/mimic.html
?? .claude/
?? docs/human-takes-protocol.md
?? scripts/analyze_human_takes.py
?? tests/test_analyze_human_takes.py
```
Se aparecer qualquer outra linha ou faltar alguma, PARE e reporte (outra sessão pode estar mexendo lá).

- [ ] **Step 2: Stage por caminho exato**

```bash
git -C "$W" add server_score_addendum.py tests/test_score_route.py web/mimic.html docs/human-takes-protocol.md scripts/analyze_human_takes.py tests/test_analyze_human_takes.py
```

- [ ] **Step 3: Conferir que `.claude/` ficou de fora**

Run: `git -C "$W" status --short`
Expected: 6 linhas começando com `A ` ou `M ` e uma `?? .claude/`. Se `.claude/` aparecer staged: `git -C "$W" reset -- .claude` e reconfira.

- [ ] **Step 4: Commit**

```bash
git -C "$W" commit -m "wip(scorer): coleta de take humano — protocolo, analyze script, checkbox salvar

Preservacao de WIP que nunca virou PR (estava so no worktree). Sem prova
rodada aqui; vira rodada propria depois da PR do jogo de festa.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Confirmar**

Run: `git -C "$W" log --oneline -1 && git -C "$W" status --short`
Expected: primeira linha começa com `wip(scorer)`; status mostra só `?? .claude/`. **Sem push.**

---

### Task 3 (VERIFICADOR — Opus, não o executor): prova de browser, testes de backend, PR

**Files:** nenhum editado de forma permanente (a guarda é comentada e restaurada para o controle negativo).

- [ ] **Step 1: Pré-requisitos gitignored**

Run: `python scripts/fetch_ui_sfx.py && python scripts/fetch_mimic_refs.py && ls web/sfx/*.mp3 | wc -l && ls input/mimic_refs/*.wav | wc -l`
Expected: ambos os contadores > 0.

- [ ] **Step 2: Testes de backend**

Run: `python -m pytest tests/test_score_route.py tests/test_mimic_refs_route.py -q`
Expected: `N passed`; publicar `N/N` com o total reportado pelo pytest (contexto anterior: 34).

- [ ] **Step 3: Subir o servidor e abrir `party.html`**

Subir `server.py` via `preview_start` e abrir `/static/party.html` no Browser pane.

- [ ] **Step 4: Prova positiva/negativa da guarda, com cardinalidade**

| # | Estado | Ação | Esperado |
|---|---|---|---|
| a | setup, antes de Começar | reload | recarrega **sem** diálogo |
| b | 1 jogador, 1 rodada, clicar Começar, sem gravar | reload | diálogo de saída (cancelar) |
| c | mesma partida, gravar 1 take, chegar na tela final | reload | recarrega **sem** diálogo |
| d | **controle negativo:** comentar a linha `if (rodadaAtual > 0 ...` em `party.html`, hard-reload, repetir (b) | reload | recarrega **sem** diálogo |
| e | restaurar (`git checkout -- web/party.html`), hard-reload, repetir (b) | reload | diálogo aparece |

Publicar: 5/5 estados examinados e o resultado de cada um. Se o browser embarcado não renderizar o diálogo nativo, usar `navigate` sem `force`: erro "Leave site?" em (b)/(e) e sucesso em (a)/(c)/(d) é a mesma prova.

- [ ] **Step 5: Pontos no título**

Em (b) o título termina com `(0 pts)`; com ≥2 rodadas, o título da rodada 2 mostra o total da rodada 1. Ler via `get_page_text`, não screenshot.

- [ ] **Step 6: Abrir a PR**

Push: `git push -u origin claude/party-game-gaps-brainstorm-f33062`.
Depois `gh pr create --base main` com título
`feat(party): jogo de festa — backend, tema bar-de-karaoke, guarda beforeunload`
e corpo (substituir `N/N` pelo número do Step 2):

```
## O que entra
- fadb6dc3 backend do jogo: rotas /api/mimic_refs, web/party.html, web/refs.html
- 8b106b04 tema bar-de-karaoke, contador animado, sfx, crossfade
- guarda beforeunload na partida em andamento + pontos acumulados no titulo (spec: docs/superpowers/specs/2026-09-14-party-game-gaps-design.md)

## Prova
- backend: N/N
- browser: 5/5 estados da guarda (incl. controle negativo), titulo com pontos

## Fora
- sessionStorage (celular), botao "Trocar clipe", trilha de take humano (WIP preservado em claude/sound-library-party-game-033efd)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
