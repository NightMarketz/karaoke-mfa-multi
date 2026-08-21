# Prompt para a próxima sessão

> Copie tudo abaixo da linha.

---

Estou continuando um motor de jogo de karaoke que compara a voz do jogador com a melodia
da música em tempo real. Ele está construído e testado, mas **nunca foi jogado por uma
pessoa cantando de verdade** — essa é a lacuna central.

## Onde o trabalho vive

- **Worktree:** `C:/rk/karaoke-voice-game`, branch `feat/karaoke-voice-game`
- Caminho curto e fora do OneDrive de propósito (MAX_PATH e desidratação do OneDrive
  produzem ENOENT falso)
- `jobs/` e `vendor/` dentro dela são **junções de diretório do Windows** apontando para o
  checkout principal em `C:/Users/Katz/OneDrive/Desktop/Meus projetos/karaoke-mfa-multi/`.
  Sem elas o job de teste e o modelo não existem.

**Outra sessão trabalha no checkout principal, na branch `mvp-pipeline-runner`.** Nunca
rode `git add -A`, `git add .`, `git commit -a`, `git checkout <branch>`, `git stash`, nem
`taskkill //IM python.exe` — tudo isso já causou dano nesta máquina. Sempre `git add` com
caminhos exatos; servidor, mata pelo PID.

## Estado

42 commits, HEAD em `56eba91e`. **782 testes Python** (`python -m pytest tests/ -q`, o
repositório inteiro) e **69 testes JavaScript**
(`node --test tests/game-scoring.test.mjs tests/game-pitch.test.mjs tests/game-assist.test.mjs`).
Árvore limpa.

Para jogar: `python server.py`, depois `http://localhost:5000/job/202608200001/game`.
O id é `202608200001` e **não** `publi-bet` — `JOB_ID_RE` exige 12 caracteres hexadecimais
e recusa o segundo. `jobs/202608200001` é uma junção para `jobs/publi-bet`.

## O que existe

**Pipeline (Python):** o ROSVOT transcreve notas do vocal isolado; `scripts/melody_anchor.py`
ancora nas sílabas do `analysis.json`; `scripts/s05b_melody.py` escreve `melody.json` e está
registrado no `build_stage_plan` na posição 55, entre `analyzing` e `generating`. O estágio é
**best-effort**: se o ROSVOT falhar, loga, não escreve o arquivo e sai com 0, para não impedir
a entrega do vídeo.

**Navegador (JavaScript, sem bundler):** `game-scoring.js` tem as regras de pontuação puras;
`game-pitch.js` tem o detector NSDF mais mediana e histerése; `game-assist.js` tem
calibração de latência, detecção de vazamento e transposição ofertada; `game.js` é só o
glue — relógio, playback, captura, desenho. `game.css` e `templates/game.html` têm o design.

**Regra de ouro do projeto:** nenhuma regra de pontuação mora no `game.js`. Ela vive nos
módulos puros, que rodam no terminal. Se você se pegar escrevendo um limiar de acerto
dentro do glue, está no lugar errado.

## A lacuna que importa

**Ninguém cantou nisso ainda.** Todas as verificações foram por medição, teste e simulação;
nenhum agente tem voz. O usuário tentou testar duas vezes e nas duas o navegador serviu
JavaScript antigo do cache — já corrigido em `56eba91e`, mas a partida real segue não feita.

Três coisas só se descobrem cantando:

1. **A latência é jogável?** A calibração automática correlaciona os ataques cantados com
   os inícios de nota após a primeira linha, e oferece o ajuste. Nunca foi exercitada com
   voz real.
2. **O zumbido pontua?** Zumbir uma nota contínua num trecho de rap tem que dar perto de
   zero. É o teste da correção mais importante da sessão: a pista de ritmo media *presença*
   de voz e um drone de 65 Hz acertava 138 de 138 notas de rap, tirando 100% numa música só
   de rap. Passou a exigir **ataque** (transição silêncio→voz). Nenhuma partida normal
   exercita isso, porque nelas você ataca as sílabas naturalmente.
3. **O aviso de vazamento funciona?** Ele mede 2 segundos de silêncio no início e avisa se
   a música está entrando pelo microfone. Precisa do par: com fone não avisa, no
   alto-falante avisa. Um lado só não prova nada.

## Como esta sessão trabalhou, e por quê

Estas regras pegaram defeitos reais o dia inteiro. Mantenha-as.

**Todo teste de lógica não-trivial tem controle negativo.** Sabote o alvo, confirme que o
teste fica vermelho, desfaça, confirme verde. Cerca que nunca foi vista vermelha não é
cerca. Isso pegou, entre outros: um teste de travessia de diretório que passava sem a
validação (o 404 vinha do arquivo não existir, não da proteção — e havia vazamento real por
`..%5C` no Windows), e três testes que afirmavam o literal `50` em vez da constante.

**Todo número sai com denominador, e a soma das partes fecha com o total.** "455 de 627",
nunca "455". Isso pegou uma divergência de contagem de testes que durou horas: eu reportava
`pytest tests/` (778) e um subagente reportava `pytest` na raiz (838). Nenhum dos dois
estava errado — os dois mediam populações diferentes sem nomear qual.

**Número vindo de subagente ou de relatório é alegação, não medição.** Reconcilie antes de
repassar. Um implementador declarou um passo feito sem ter rodado, e o passo escondia dois
bugs de fronteira com o sistema operacional.

**Corrija a causa raiz, não o sintoma, e varra a classe inteira.** Um `.catch()` foi
aplicado em 1 de 3 chamadores e o defeito voltou pelos irmãos.

## Onde eu já errei, para você não repetir

- **Apliquei regra de pontuação na camada de apresentação.** O desenho usava `midi % 12`
  espelhando o dobramento de oitava da pontuação. A nota ignora oitava de propósito; o
  desenho não pode. 86 de 454 pares vizinhos saltavam mais de 200px com 2 semitons ou menos
  de diferença na música.
- **Tentei remontar a letra a partir das notas.** Impossível: mapeamento esparso e
  muitos-para-um. Das 48 linhas remontadas, 1 batia. A letra vem do `analysis.json`, pelo
  campo `lines` do `melody.json`.
- **Publiquei conclusões que a própria aritmética contradizia**, mais de uma vez. Uma vez
  dizendo que o piso do herói era maior que o do widget com os números 150 e 144 na mesma
  frase; outra dizendo que a linha do tempo estava "comprimida" antes de medir a deriva.
- **Chamei cache de bug de lógica** e quase mandei consertar o lugar errado. Medi primeiro:
  a lógica errava 1 amostra de 48.

## Aberto

- **`PRODUCT.md` não existe.** A revisão de acabamento do design mantém `persistence` em
  FAIL por isso. Decisão registrada, não esquecimento.
- **Cinco Minor diferidos** no ledger em `.superpowers/sdd/2026-08-20-karaoke-voice-game/progress.md`
  (diretório gitignored), todos triados como não-bloqueantes pela revisão final de branch.
- **41 diretórios `tmp*`** vazados em `vendor/ROSVOT/out/` pela suíte de testes.
- **Sem realce progressivo na letra.** A linha aparece como texto estático; não há varredura
  sílaba a sílaba conforme se canta. Nunca foi construído — se o usuário pedir "a letra não
  acompanha", é isto, e é trabalho novo.
- **SwiftF0 investigado e não adotado.** Medido no navegador: 7,9 ms por chamada na menor
  janela, 47% do orçamento de quadro, contra 0,38 ms do NSDF atual. Ver
  `docs/superpowers/plans/assets/spike-swiftf0.md`. O caminho viável, se um dia precisar, é
  Web Worker a 20 Hz.

## Fragilidade de ambiente

O ROSVOT só roda nesta máquina com um patch de fallback para CPU (não há GPU NVIDIA aqui).
O patch está versionado em `vendor-patches/rosvot-cpu-fallback.patch` e a reaplicação foi
verificada byte a byte. `vendor/ROSVOT` é gitignored, então um clone novo precisa refazer o
setup descrito em `docs/superpowers/plans/assets/rosvot-schema.md`.

## Documentos que valem ler antes de mexer

- `docs/superpowers/specs/2026-08-20-karaoke-voice-game-design.md` — o contrato, atualizado
  três vezes durante a execução
- `docs/superpowers/plans/assets/pesquisa-lideres-achados.md` — o que o UltraStar Deluxe faz,
  lido no código-fonte; validou nosso dobramento de oitava e nossas duas pistas, e contradisse
  nosso teto de pontos do rap
- `docs/superpowers/plans/assets/publi-field-report.md` — os números medidos na música de teste
- `docs/superpowers/plans/assets/spike-swiftf0.md` — por que não trocamos o detector

## O que eu quero agora

[Descreva aqui o que você quer nesta sessão. Se for testar cantando, o roteiro está no
final do `publi-field-report.md`, e o teste do zumbido é o que mais importa.]
