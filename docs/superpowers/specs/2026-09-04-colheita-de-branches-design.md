# Colheita de branches: critério de integração e de morte

Data: 2026-09-04
Linhagem alvo: `mvp-pipeline-runner` (checkout principal)
Origem: redesenho do processo de trabalho, após verificação medida do repositório

## 1. Problema

Quatro sintomas relatados, uma raiz só: **não existe tronco**. Trabalho sai para um
worktree isolado e nunca volta. Daí decorrem os quatro:

| Sintoma | Como aparece |
| --- | --- |
| Nada integra | 2 merges em 270 commits |
| Perdi o estado | 42 branches locais, 15 worktrees, nenhum lugar diz o que cada uma é |
| Retrabalho e regressão | docs descrevem um pipeline que não roda; sessões re-resolvem |
| Ritual caro demais | 19 planos + 8 specs + 7 ADRs no tronco, para pouco código integrado |

O aparato de planos e specs cresceu para compensar a ausência de realidade
compartilhada. Não é o problema; é a cicatriz dele.

## 2. Linha de base medida (2026-09-04)

Tudo abaixo foi medido nesta data, não estimado.

**Estrutura do repositório**
- 56 refs no total: 42 locais + 14 remotas.
- **2 raízes git sem ancestral comum.** Linhagem MAIN (raiz `4828ebd6`, 2026-03-14):
  35 de 56 refs. Linhagem MASTER (raiz `1c0165dc`, 2026-05-21): 21 de 56.
- A raiz **mais velha** é a linhagem **morta**. Os últimos 30 commits estão
  30 de 30 na linhagem MASTER.
- `mvp-pipeline-runner` está **112 commits à frente de `master`**. É o tronco de
  fato, nunca declarado como tal.

**As 42 branches locais, contra o tronco**
- **29 de 42 não têm ancestral comum** com `mvp-pipeline-runner`. `git merge` não
  se aplica a elas.
- **13 de 42 são mergeáveis**; dessas, **10 têm trabalho de fato** (ahead > 0).
- **16 de 42 estão congeladas em 2026-03-15**, todas sem ancestral. É a data da
  morte da linhagem MAIN.
- Concentração do valor não colhido: `feat/karaoke-voice-game` (ahead 46, behind 8),
  `claude/flf2v-takes-render` (ahead 34, behind 112),
  `claude/anime-compositing-satsuei-2585b3` (ahead 18, behind 112).

**Comando de teste**
- O canônico é `pytest tests`, documentado em `spec/TEST_PLAN.md:8`, presente em
  5 de 42 branches locais — nenhuma delas alcançável por quem lê só o `README.md`.
- `pytest` na raiz mede outra população: transforma `pytest.importorskip` em erro
  de coleta. Foi a origem da divergência 778/838.

**Deriva da documentação**
- `README.md` (linhagem MAIN) lista 12 estágios de pipeline. `run_pipeline.py`
  monta 13, com outros nomes. Batem **3 de 12**.
- A linhagem viva tem 7–8 estágios `s0x` em `scripts/pipeline_runner.py`.

## 3. Decisões fechadas

| Decisão | Escolha | Observação |
| --- | --- | --- |
| Formato de trabalho | Paralelo + sessão de colheita | escolhido sobre serial-com-tronco e sobre ferro-velho sob demanda |
| Tronco | `mvp-pipeline-runner` | constatação (112 à frente de `master`), não preferência |
| Refs protegidas | `mvp-pipeline-runner`, `master`, `main` | nunca mortas automaticamente |
| Critério de morte | Relógio + linhagem, mecânicos; sobrevivência justificada por frase | não havia critério anterior; este é novo, não recuperado |
| Janela do relógio | 14 dias sem commit | ver Lacuna L1 |
| Destino do que morre | `git tag attic/<nome>` e `git branch -D <nome>` | o commit sobrevive na tag; nada é perdido |
| Portão de merge | `pytest tests` verde **no resultado do merge** | não na branch isolada |
| Gatilho da colheita | Antes de despachar uma frente nova | não é calendário |

## 4. Os três portões, na ordem

**P1 — Linhagem (mecânico).** Branch sem ancestral comum com o tronco sai da fila
de colheita. Não é candidata a merge, por impossibilidade estrutural, não por
julgamento de valor. Efeito hoje: **29 de 42 saem sem inspeção humana**.

**P2 — Relógio (mecânico).** Branch sem commit há mais de 14 dias vira
`attic/<nome>` e a branch é apagada. Efeito hoje: das 13 mergeáveis, 2 são protegidas (`mvp-pipeline-runner`, `master`); das 11 restantes, mata 8.

**P3 — Sobrevivência (humano).** O que chega aqui exige uma frase sua dizendo o
que a branch entrega. Sem frase, morre igual. Efeito hoje: **3 branches** chegam
a P3 — `claude/flf2v-takes-render`, `claude/anime-compositing-satsuei-2585b3`,
`feat/karaoke-voice-game`.

**Resultado sobre a listagem:** `git branch` sai de 42 linhas para **5** — as 3
sobreviventes mais as 2 protegidas locais (`mvp-pipeline-runner`, `master`).

Nada é perdido em P1 ou P2. A tag `attic/<nome>` segura o commit indefinidamente;
o que muda é que ele some da listagem de branches e do espaço mental.

## 5. Portão de merge

Sequência, no tronco:

1. `git merge <branch>` no tronco.
2. `pytest tests` — o comando exato, com o argumento.
3. Verde: commita. Vermelho: desfaz o merge, a branch volta para P3 com a falha
   registrada na frase.

A verificação roda **no resultado do merge**, nunca na branch isolada. Suíte verde
em duas branches separadas não diz nada sobre a união das duas.

## 6. Estado: gerado, nunca mantido

O estado é um comando, não um arquivo. Imprime, por branch:
`linhagem | ahead/behind vs tronco | data do último commit | assunto`.

Não existe arquivo a atualizar, logo não existe arquivo a apodrecer. É a correção
direta do que aconteceu com o `README.md`, que descreve há meses um pipeline de 12
estágios que não roda.

## 7. Gatilho da colheita

**Antes de despachar uma frente nova.** Você só abre a branch N+1 depois de
resolver o destino das N existentes. Auto-limitante: não precisa de lembrete, não
vira sessão semanal que se pula, e o custo de acumular recai sobre quem acumula.

## 8. Worktrees

Hoje 15 ativos, com 3 pares apontando para o mesmo commit. Depois de P1 e P2:
`git worktree prune`, e remoção manual dos que apontam para branch morta.

## 9. Onde as regras moram

No `CLAUDE.md` da raiz do tronco (já existe, junto com `AGENTS.md`). Uma seção
curta: qual é o tronco, qual é o comando de teste com o argumento, e qual é o
gatilho da colheita.

Não vira skill. São fatos curtos, verdadeiros em toda sessão, sobre todo o repo —
o mecanismo certo para isso é a linha no `CLAUDE.md`, não um procedimento
acionado por intenção.

## 10. Fora de escopo

- **Consolidar as duas linhagens.** O desenho arquiva a MAIN; não a migra.
- **Redefinir o produto.** O que o projeto deve ser (alinhamento vs. vídeo
  generativo) foi explicitamente adiado.
- **Corrigir o `README.md`.** Necessário e conhecido, mas é trabalho de
  repositório, não de processo.
- **Hook de enforcement.** Os portões dependem de você rodá-los. Nenhum é
  garantido pela ferramenta. Ver Lacuna L3.

## 11. Lacunas declaradas

**L1 — A janela de 14 dias é proposta, não medida.** Não existe dado sobre quanto
tempo uma frente sua leva para amadurecer. 14 dias foi escolhido porque, somado a
P1, deixa 3 branches vivas hoje — um número que cabe na tela. Se frentes legítimas
começarem a morrer no relógio, o número está errado, não a regra.

**L2 — O que fazer com as 29 sem ancestral.** O desenho as arquiva. Não decide se
algo dentro delas merece ser portado à mão para o tronco. Decisão adiada, por
branch, sob demanda — e porte é trabalho novo, não colheita.

**L3 — FECHADA em 2026-09-04.** Linha de base do tronco, medida com `pytest tests`
sobre 67 arquivos `test_*.py`:

- coletados: `758` itens
- passaram: `756` de `758`
- falharam: `0` de `758`
- pulados (skipped): `2` de `758` (`tests/test_clean_outputs_integration.py:99` —
  fixture real do Struggle ausente; `tests/test_review_wizard_server.py:1727` —
  fixture real com output.mp4/output.ass indisponível)
- erros de coleta: `0`
- soma: `756` (passaram) + `0` (falharam) + `2` (pulados) = `758`

O portão de merge compara contra esses números. Merge que não aumente `0` falhos
passa, mesmo com os 2 skips herdados; merge que aumente falhos, ou reduza os itens
coletados abaixo de `758` sem justificativa, reprova.
