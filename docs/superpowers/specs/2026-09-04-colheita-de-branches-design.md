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

**As 43 branches locais, contra o tronco** — re-medido na Rodada de correção
final com `python scripts/branch_harvest.py`; a diferença de 42 para 43 é a
própria branch `claude/branch-harvest`, que passou a existir para fazer esta
medição:
- **29 de 43 não têm ancestral comum** com `mvp-pipeline-runner`. `git merge` não
  se aplica a elas.
- **14 de 43 são mergeáveis**; dessas, **11 têm trabalho de fato** (ahead > 0) —
  `claude/branch-harvest` é a que se somou.
- **16 de 43 estão congeladas em 2026-03-15**, todas sem ancestral. É a data da
  morte da linhagem MAIN.
- Concentração do valor não colhido: `feat/karaoke-voice-game` (ahead 46, behind 10),
  `claude/flf2v-takes-render` (ahead 34, behind 114),
  `claude/anime-compositing-satsuei-2585b3` (ahead 18, behind 114).

**Comando de teste**
- O canônico é `pytest tests`, documentado em `spec/TEST_PLAN.md:8`, presente em
  5 de 43 branches locais — nenhuma delas alcançável por quem lê só o `README.md`.
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
julgamento de valor. Efeito hoje: **29 de 43 saem sem inspeção humana**.

**P2 — Relógio (mecânico).** Branch sem commit há mais de 14 dias vira
`attic/<nome>` e a branch é apagada. Efeito hoje: das 14 mergeáveis, 2 são protegidas (`mvp-pipeline-runner`, `master`); das 12 restantes, mata 8.

**P3 — Sobrevivência (humano).** O que chega aqui exige uma frase sua dizendo o
que a branch entrega. Sem frase, morre igual. Efeito hoje: **4 branches** chegam
a P3 — `claude/branch-harvest` (esta mesma, a que fez a medição),
`claude/flf2v-takes-render`, `claude/anime-compositing-satsuei-2585b3`,
`feat/karaoke-voice-game`.

**Resultado sobre a listagem:** `git branch` sai de 43 linhas para **6** — as 4
sobreviventes mais as 2 protegidas locais (`mvp-pipeline-runner`, `master`).
(Re-medido na Rodada de correção final: a diferença de 42→43 e 5→6 em relação à
versão anterior deste spec é a própria branch `claude/branch-harvest`.)

Nada é perdido em P1 ou P2. A tag `attic/<nome>` segura o commit indefinidamente;
o que muda é que ele some da listagem de branches e do espaço mental.

## 5. Portão de merge

O portão é **relativo**, não um limiar absoluto — `pytest.importorskip` faz a
contagem de coletados depender do que está importável naquela máquina naquele
dia, então um número fixo (`758`, ou qualquer outro) reprovaria por diferença de
ambiente, não por regressão. Duas medições **no mesmo shell**, minutos de
diferença: o ambiente cancela por construção.

Sequência, no tronco:

1. Antes de mergear: `pytest tests` — anote coletados, passaram, falharam,
   pulados e subtests passados.
2. `git merge <branch>` no tronco.
3. `pytest tests` de novo, **no mesmo shell** do passo 1.
4. Passa se `falharam` não aumentou, `coletados` não diminuiu, e subtests não
   diminuíram. Reprova caso contrário — e a reprovação desfaz o **merge**,
   nunca o número: `git merge --abort` (ou reset ao commit anterior), a branch
   volta para P3 com a falha registrada na frase.

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

**L3 — FECHADA em 2026-09-04. Portão trocado de absoluto para relativo (Rodada de
correção final).** `758` era propriedade da máquina daquele momento, não do
código: `pytest.importorskip` faz o número de coletados depender do que está
importável, e por isso não pode ser um limiar fixo. O portão de merge (§5) agora
mede duas vezes no mesmo shell — antes e depois do merge — e compara a diferença,
nunca um número absoluto contra outro dia.

Os números abaixo, medidos com `pytest tests` sobre 67 arquivos `test_*.py`,
ficam como **contexto histórico do que o tronco valia naquele dia**, não como
limiar:

- coletados: `758` itens
- passaram: `756` de `758`
- falharam: `0` de `758`
- pulados (skipped): `2` de `758` (`tests/test_clean_outputs_integration.py:99` —
  fixture real do Struggle ausente; `tests/test_review_wizard_server.py:1727` —
  fixture real com output.mp4/output.ass indisponível)
- erros de coleta: `0`
- soma: `756` (passaram) + `0` (falharam) + `2` (pulados) = `758`
- subtests passados: `293` de `293` (0 falharam) — não fazia parte da medição
  original; ver L3/A9 na Rodada de correção final. Um teste que itera sobre uma
  coleção que virou vazia continua verde e some `293` → `0` sem mover nenhum dos
  números acima, por isso o portão de merge (§5) também compara subtests.
- ambiente: nenhum ambiente conda declarado do projeto (`karaoke_env`, `demucs_env`, `mfa_env`, base do miniforge3) tem `pytest` instalado; a medição usou o `pytest` resolvido pelo `PATH` (venv `hermes-agent`, pytest 9.0.2, Python 3.11.9). Reproduzir esta linha de base exige localizar (ou provisionar) um interpretador com pytest equivalente — outro ambiente pode mudar coletados/pulados por diferença de ambiente, não por regressão.

**L4 — DECLARADA, não resolvida.** O projeto não declara nenhum ambiente onde o
próprio comando de teste roda. Nenhum dos ambientes conda declarados
(`karaoke_env`, `demucs_env`, `mfa_env`) tem `pytest`. O portão relativo (§5)
contorna isso — as duas medições rodam no mesmo shell, seja ele qual for — mas a
causa raiz continua: quem clonar o repositório não tem como rodar `pytest tests`
seguindo só o que o repositório declara. É trabalho de repositório, fora deste
plano.
