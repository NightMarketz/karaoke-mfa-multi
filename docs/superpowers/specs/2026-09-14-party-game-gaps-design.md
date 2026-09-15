# Lacunas do jogo de festa após o refresh visual — desenho

Data: 2026-09-14. Base: commits `fadb6dc3` (backend + party/refs) e `8b106b04`
(tema bar-de-karaoke), ambos ainda sem PR. Dispositivo alvo do `party.html`:
**notebook na mesa** (decisão do usuário) — recarregar no meio da partida é
acidente raro, não fluxo.

## Decisão por lacuna

| # | Lacuna | Decisão |
|---|---|---|
| 1 | Sem PR | Abrir PR agora, com 1 commit extra contendo #2 e #4. |
| 2 | Estado só em memória | Guarda `beforeunload` enquanto há partida em andamento. Sem `sessionStorage`. |
| 3 | Clipe repetido só avisa por `alert()` | Não entra. Repetição é inevitável quando `clipes < rodadas`; o aviso já diz isso. |
| 4 | Placar acumulado só no resumo | Uma linha: título da rodada mostra `(N pts)` do jogador da vez. |
| 5 | WIP de take humano sem commit | Não entra nesta rodada. Só preservar: commit `wip:` no worktree dele. |

## #2 — guarda `beforeunload`

Em `web/party.html`, logo após o bloco de `let` de estado:

- Handler em `window` para `beforeunload`.
- Condição de disparo: `rodadaAtual > 0 && rodadaAtual <= numRodadas`.
  `proximaRodada` incrementa além de `numRodadas` antes de chamar `mostraFinal`,
  então esse intervalo é exatamente "partida em andamento" — sem depender do
  `hidden` da seção, que o `crossfade` só vira 200 ms depois. Fora disso
  (setup, tela final) o reload passa sem diálogo.
- Ao disparar: `e.preventDefault()` (diálogo nativo; o texto não é
  customizável em browsers atuais — não tentar).
- Comentário `ponytail:` no handler dizendo que é notebook-only e que celular
  (iOS não dispara `beforeunload`) pede `sessionStorage`.
- O comentário atual "recarregar a pagina perde a partida" fica, ajustado
  para dizer que a guarda só evita o acidente, não recupera.

## #4 — pontos no título

Em `proximoJogadorDaRodada`, o título vira
`Rodada X/Y — clipe "…" — vez de ${j.nome} (${j.pontos} pts)`.
`j.pontos` já é o acumulado das rodadas anteriores (zerado em `iniciaPartida`).

## #5 — preservar WIP

No worktree `.claude/worktrees/sound-library-party-game-033efd` (branch
`claude/sound-library-party-game-033efd`): `git add` dos 3 modificados
(`server_score_addendum.py`, `tests/test_score_route.py`, `web/mimic.html`) e
3 novos (`docs/human-takes-protocol.md`, `scripts/analyze_human_takes.py`,
`tests/test_analyze_human_takes.py`). **Não** adicionar `.claude/`. Commit
`wip(scorer): coleta de take humano — protocolo, analyze script, checkbox salvar`.
Sem push obrigatório, sem PR.

## Prova

`party.html` não tem teste JS; a guarda é 4 linhas com uma condição. Prova é
manual no browser, com controle negativo:

| Estado | Ação | Esperado |
|---|---|---|
| setup (antes de Começar) | F5 | recarrega sem diálogo |
| rodada 1, jogador 1, antes de gravar | F5 | diálogo "sair?" |
| tela final | F5 | recarrega sem diálogo |
| **controle negativo:** handler comentado, rodada 1 | F5 | recarrega **sem** diálogo |

Depois do controle negativo, restaurar o handler e repetir a linha 2.

Backend: `pytest tests/test_score_route.py tests/test_mimic_refs_route.py`
— publicar `N/34` passando.

Pré-requisitos pra abrir no browser: `scripts/fetch_ui_sfx.py` e
`scripts/fetch_mimic_refs.py` (sfx e refs são gitignored).

## Papéis

Opus escreve esta spec e o plano; Sonnet implementa #2, #4 e #5 e commita;
Opus roda a prova de browser (inclusive o controle negativo), roda os testes
de backend e abre a PR.

## Fora de escopo (e quando entra)

- `sessionStorage`: quando o jogo rodar em celular.
- Botão "Trocar clipe" (só antes do 1º jogador da rodada gravar): quando um
  playtest mostrar gente querendo pular clipe ruim.
- PR da trilha de take humano: rodada própria, depois desta PR.
