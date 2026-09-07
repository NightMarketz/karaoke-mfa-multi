# Hardening — fundo ilustração local

Seis itens sobre o branch já revisado: dois achados parados na revisão (P1, P2)
e quatro vindos da experiência operacional do usuário com ComfyUI (H1–H4).

Nenhuma dependência nova. Só stdlib: `json`, `os`, `random`, `shutil`, `time`,
`urllib.request`, `uuid`, `pathlib`. `copy` saiu (o `deepcopy` do
`_inject_prompt` não existe mais).

---

## P1 — `karaoke/bounce.py`: a deriva movia antes de a janela existir

**Medição de partida, reproduzida antes de tocar no código.**
`build_sendcmd([12.0, 40.0, 80.0], 1408, 792, duration=210.0)`: o primeiro
`crop w`/`crop h` caía no índice **12 de 217** comandos, e **4 dos 217** (todos
antes dele) tinham `x + w = 1410 > WORK_W = 1408` — 2px. O ffmpeg satura `x`/`y`
por quadro em vez de falhar, então o sintoma visível era deriva presa na intro,
sem erro nenhum.

**Correção.** Com deriva ativa, `eventos.insert(0, (0.0, [("w", fw), ("h", fh)]))`
antes do laço da deriva. O `sort` por tempo é estável, então o comando de
repouso fica na frente de qualquer `x`/`y` em `t=0.0` — e um onset em `t=0.0`
continua reassumindo depois dele, como antes.

**Cercas.**
- `test_deriva_move_x_e_y_e_respeita_o_limite_da_fonte` ganhou a asserção de que
  o primeiro comando emitido carrega `w`/`h` e sai em `t=0.000`.
- `test_a_janela_do_crop_nunca_estoura_a_fonte_em_nenhum_comando` (novo,
  3 parametrizações) reexecuta o script comando a comando a partir do estado
  real do filtergraph (`crop=WORK_W:WORK_H`, `x=y=0`), acompanhando o último
  `w/h/x/y` comandado, e afirma o invariante em **todo** ponto. A mensagem
  nomeia quantos comandos foram examinados e qual foi o primeiro estouro.

O teste antigo media `x` contra `max(crop w)` do arquivo inteiro — o que já
supõe que `w` foi comandado. Era exatamente essa suposição que estava falsa.

**Controle negativo.** Removida a linha do `insert(0, ...)`:

```
2 failed, 11 passed
AssertionError: primeiro comando nao estabelece a janela: '0.000 crop x 0, crop y 0;'
AssertionError: 4 de 217 comandos estouram a fonte 1408x792; primeiro: idx=8 t=8.0
                w=1408 h=792 x=2 y=0 (x+w=1410, y+h=792)
```

O número bate com a medição de partida (4 de 217, idx 8, 2px). Linha restaurada;
13 passed em `tests/test_bounce.py`.

Honestidade sobre o controle: só **1 das 3** parametrizações da varredura ficou
vermelha (a de intro longa, `[12, 40, 80] / 210s`). As outras duas têm o primeiro
onset cedo demais para acumular deriva suficiente antes do primeiro `w/h`. Elas
existem como cobertura de regressão, não como detectoras deste defeito.

---

## P2 — `tests/test_paths_contract.py`: guarda de cardinalidade tautológica

`_scripts_vivos` acrescenta `[(e, e) for e in ENTRY_POINTS]` incondicionalmente,
então `{e for _, e in SCRIPTS} == set(ENTRY_POINTS)` era verdadeiro por
construção — o regex podia parar de casar dentro do `server.py`, o fence
encolher, e o guard seguir verde.

**Correção.** A comparação passa a usar só as linhas que o regex de fato
produziu (as com prefixo `scripts/`), e reporta quantos scripts cada entry point
contribuiu; um entry point com contribuição zero falha por si.

**Controle negativo.** Regex forçado a não casar dentro do `server.py`:

```
1 failed, 21 passed        (antes: 24 passed, 2 skipped)
AssertionError: 17 scripts extraidos por entry point:
                {'run_pipeline.py': 17, 'server.py': 0};
                esperado contribuicao dos 2 entry points ('run_pipeline.py', 'server.py')
```

O fence encolheu de 19 para 17 scripts e o guard nomeou o culpado. Restaurado:
24 passed, 2 skipped.

---

## H1 — o cache do ComfyUI devolve nada, em silêncio

Reenviar um grafo idêntico faz o ComfyUI responder `execution_cached` com
`outputs: {}`. O `RuntimeError` subia, o `08b` avisava e caía no fundo chapado —
permanentemente para aquela música, sem pista nenhuma.

**Correção.** `_bust_cache(workflow) -> int` sufixa `uuid.uuid4().hex[:8]` em
**todo** `filename_prefix` do grafo, varrendo todos os nós (um grafo pode ter
mais de um `SaveImage`), e devolve quantos alterou. Chamado por `generate_image`
logo depois da injeção.

Sem conflito com o caminho de cópia da saída: `generate_image` monta `src` a
partir do `filename`/`subfolder` que o `/history` devolve, não do prefixo que
enviou. O nonce viaja pelo nome do arquivo e a cópia continua acertando o alvo.

**Testes.**
- duas submissões idênticas → dois prefixos distintos, ambos preservando o
  prefixo original (`karaoke/bg_...`);
- grafo com 5 nós, 3 deles com `filename_prefix` (`SaveImage` ×2 +
  `SaveAnimatedWEBP`): a contagem alterada tem de fechar com a contagem
  examinada, e o nonce tem de ser o mesmo nos três;
- **caso zero explícito**: grafo sem nenhum `filename_prefix` devolve `0`, não
  passa por "tudo pronto". Está no código como `ponytail:` — não há cache a sujar
  num grafo que não salva arquivo, e o sintoma vira `outputs` vazio, onde o H2
  assume;
- fiação: o teste de captura do payload confirma que o prefixo que **sai** de
  `generate_image` já vem com nonce (não só que a função isolada funciona).

## H2 — `status=success` com zero saídas

**Correção.** `_diagnostico(entry)` lê `status.status_str` e `status.messages`
inteiramente por `.get()`, junta e trunca em 600 caracteres; a `RuntimeError` de
saídas vazias passa a carregar esse texto. A linha `AVISO: fundo nao gerado
(...)` do `08b` agora diz o que o ComfyUI reclamou.

**Testes.** Entrada com `outputs: {}` e `status.messages` populado produz exceção
contendo a mensagem. Cinco parametrizações de degradação (sem `status`, `status`
nulo, sem `messages`, `messages` vazio, sem `outputs`) confirmam mensagem pobre
em vez de `KeyError` dentro do próprio caminho de erro. Mais truncamento.

## H3 — a porta não é fixa

**Correção.** `resolve_comfy_host()`: `COMFYUI_URL` literal se setada (sem
sondar), senão sonda `8188, 8000, 8001` contra `/system_stats` com 1,5 s cada, e
se nenhuma responder levanta nomeando as três **e** a variável de ambiente.
`COMFY_HOST` deletada. `generate_image(host=...)` continua pulando a resolução
inteira; a resolução acontece **depois** da injeção, então um template sem
marcador falha sem sondar porta nenhuma.

**Testes.** Env var vence sem sondar (assere lista de tentativas vazia);
3 parametrizações de sondagem verificam a **ordem** exata de tentativa e a
parada no primeiro que responde; todas mortas → erro nomeando as 3 candidatas,
com 3 de 3 sondadas.

**Prova de que nenhum teste toca a rede.** `tests/test_background.py` roda com
`socket.socket` substituído por uma classe que levanta no construtor:
`24 passed`. Controle do próprio bloqueio: `urllib.request.urlopen` contra
`127.0.0.1:8188` com o mesmo patch levanta `AssertionError: rede proibida` —
o bloqueio funciona, então o verde acima significa alguma coisa.

## H4 — marcador, nunca id de nó

**Correção.** `_inject_prompt(workflow_text: str, prompt: str) -> dict` opera no
**texto** do template. `%prompt%` (dentro de aspas) entra com
`json.dumps(prompt)[1:-1]`; `%seed%` (número cru, sem aspas) recebe
`random.randrange(0, 2**32)`. `%prompt%` ausente levanta `ValueError`.
`COMFY_PROMPT_NODE` deletada.

**Ordem das duas substituições importa e é deliberada:** `%seed%` primeiro. O
prompt é texto livre escrito por um LLM; trocá-lo antes deixaria um `%seed%`
vindo do brief virar número. Na ordem escolhida, o valor injetado do seed é só
dígitos e não pode conter `%prompt%`. Descoberto porque o teste de prompt hostil
inclui um `%seed%` de propósito — e ficou vermelho na primeira ordem.

**Testes.** Prompt com `\` **e** `"` **e** `%seed%` faz o round-trip e a asserção
é sobre a estrutura **parseada** (`grafo["6"]["inputs"]["text"] == hostil`), não
sobre substring do texto cru. Seed sai `int` (não `bool`, não `str`), na faixa, e
5 chamadas produzem mais de um valor. Template sem `%prompt%` levanta. Os dois
testes antigos de injeção por id de nó foram substituídos; o teste de vazamento
da letra crua passou a usar o template marcado e host explícito.

**README.** A instrução "confira o id do nó" estava errada e saiu. No lugar: uma
tabela com as duas trocas exatas a fazer no export, o aviso de que `%seed%` sem
aspas deixa o arquivo temporariamente fora do JSON válido (é o esperado), a
declaração de que um export cru **não** funciona, e a nova precedência de porta
(`COMFYUI_URL` → sondagem 8188/8000/8001). O pré-requisito de job real também
foi atualizado.

---

## Testes — com denominadores

Baseline do branch, antes de qualquer alteração:

```
3 failed, 102 passed, 2 skipped, 1 xfailed  (108 coletados)
```

Depois de tudo:

```
3 failed, 122 passed, 2 skipped, 1 xfailed  (128 coletados)
```

Comando (o dos dois lados):
`pytest tests/ --ignore=tests/integration --ignore=tests/test_ass_builder.py --ignore=tests/test_critical_pipeline.py`

**As 3 falhas são as mesmas 3 de antes**, todas em arquivos que este branch
nunca tocou:

| falha | arquivo |
|---|---|
| `TestDriftClamped::test_max_duration_reduced` | `tests/test_music_gap_corrector.py` |
| `TestCorrectionReport::test_drift_report_complete` | `tests/test_music_gap_corrector.py` |
| `TestShouldFail::test_threshold_sensitivity` | `tests/test_qc.py` |

**Reconciliação dos +20 passando**, por outro caminho que não a diferença dos
totais:

| arquivo | antes | depois | delta |
|---|---|---|---|
| `tests/test_bounce.py` | 10 | 13 | +3 (varredura ×3 parametrizações) |
| `tests/test_background.py` | 7 | 24 | +17 |
| `tests/test_paths_contract.py` | 24 (+2 skip) | 24 (+2 skip) | 0 (guard reescrito, não somado) |

3 + 17 + 0 = 20, e 102 + 20 = 122. Fecha.

`tests/test_critical_pipeline.py` continua excluído (fecha o stdout
compartilhado); fora de escopo, não foi tocado.

## Arquivos alterados

| arquivo | item |
|---|---|
| `karaoke/bounce.py` | P1 |
| `tests/test_bounce.py` | P1 |
| `tests/test_paths_contract.py` | P2 |
| `karaoke/background.py` | H1, H2, H3, H4 |
| `tests/test_background.py` | H1, H2, H3, H4 |
| `README.md` | H3, H4 |

`config/comfy_workflow.json` continua **não existindo** — precisa de um humano
com a GUI do ComfyUI aberta. Nenhuma migração pendente, mas o README já descreve
o formato novo.

## Commits

```
7ce75d14 fix(bounce): estabelece o crop de repouso em t=0 antes da deriva
b700ca16 test: guarda de cardinalidade do fence deixa de ser tautologica
e2d40741 fix(background): injeta por marcador %prompt%/%seed%, nunca por id de no
ddfb71a1 fix(background): quebra o cache do ComfyUI e reporta o que ele reclamou
c46778c7 feat(background): resolve o host do ComfyUI por COMFYUI_URL ou sondagem
9c731128 docs: README manda marcar o template do ComfyUI e descreve a descoberta de porta
```

## Preocupações

1. **A falha explícita do H4 não é explícita no nível do pipeline.** O
   `except Exception` do `08b` engole o `ValueError` de template sem marcador,
   como engole tudo — é a constraint do branch, e está certa. Mas isso quer dizer
   que "falhar alto em vez de renderizar o placeholder" se traduz numa linha de
   log, não num exit code. Se o usuário não ler o log do estágio 11, um template
   mal marcado se parece com ComfyUI fora do ar.

2. **Nada disso foi executado contra um ComfyUI real.** Vale para todos os
   quatro itens de hardening. Em particular, não foi medido de fato que sujar
   `filename_prefix` basta para invalidar o cache do ComfyUI (H1) — isso vem da
   experiência do usuário no projeto irmão, não de medição aqui. O mesmo para o
   formato do objeto `status` no `/history` (H2): o código lê tudo por `.get()`
   justamente por isso, mas o texto que o usuário vai ler no aviso não foi visto.

3. **`COMFY_PROBE_SECONDS = 1.5` × 3 candidatas = até 4,5 s** no pior caso (tudo
   fora do ar), uma vez por job. Aceitável, mas é tempo gasto antes de cair no
   fundo chapado. Se incomodar, `COMFYUI_URL` pula a sondagem inteira.

4. **A varredura de `_bust_cache` supõe que `filename_prefix` é o campo certo.**
   Um nó customizado que salve arquivo com outro nome de campo passa batido e
   devolveria 0 alterações sem ninguém notar. O teste do caso zero documenta o
   buraco; fechar de verdade exigiria conhecer o grafo real.

5. **Um `%prompt%` fora do nó positivo seria substituído também.** A substituição
   é textual e global. Se o usuário marcar o prompt negativo por engano, o brief
   vai para os dois. Nada detecta isso — está no README como instrução, não como
   verificação.
