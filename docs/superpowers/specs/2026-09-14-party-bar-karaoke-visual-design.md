# Refresh visual "bar de karaokê": jogo de festa + gravação

Brainstorm em 2026-09-14, com companion visual (mockups de 4 direções — Neon
arcade, Confete quente, Bar de karaokê, Minimal com 1 acento — decidido: **Bar
de karaokê**). Contexto: `web/party.html`, `web/mimic.html` e `web/refs.html`
foram entregues funcionais mas visualmente crus (CSS minimalista
system-ui/preto-e-branco, sem animação, sem áudio de feedback).

## Escopo

**Dentro:**
1. Identidade visual "bar de karaokê" em `party.html` e `mimic.html`.
2. Animação de contador crescente em todo número de nota exibido.
3. 2 efeitos sonoros (ding de pontuação, aplauso na tela final).
4. Crossfade simples nas trocas de tela/estado.

**Fora (deliberado):**
- `refs.html` (biblioteca de sons) não recebe o tema escuro/dourado — é tela
  de gerenciamento (upload/apagar), usada fora do momento de "performance".
  Decisão do humano: reservar o clima teatral pra `party.html`/`mimic.html`.
  Ajuste pontual de espaçamento nela, se necessário, mas sem repintar.
- Controle de mute/volume — silenciar a aba do navegador já resolve na v1.
- Karaoke mode dentro do jogo de festa (fora desde o levantamento original).
- Qualquer coisa do roteiro de coleta de take humano
  ([[karaoke-scorer-followups]], `docs/human-takes-protocol.md`) — trilha
  separada, não se mistura com este refresh visual.

## 1. Identidade visual

Tokens de cor/tipografia, num `web/theme-karaoke.css` novo, compartilhado via
`<link rel="stylesheet">` em `party.html` e `mimic.html` (hoje cada arquivo é
autocontido; isso é a primeira folha de estilo compartilhada do projeto —
justificada porque agora 2 arquivos precisam do MESMO tema, não é
especulação):

```css
:root {
  --bg: #1c1410;        /* fundo, escuro e quente */
  --bg-card: #2b2018;   /* linhas/cartões, um tom acima do fundo */
  --fg: #f2e2c4;        /* texto principal, creme */
  --accent: #e8b04b;    /* dourado de palco — títulos, destaques, vencedor */
  --accent-soft: rgba(232, 176, 75, .35); /* glow, nunca borda lateral grossa */
}
body { background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, sans-serif; }
h1, h2, .destaque { font-family: Georgia, 'Times New Roman', serif; color: var(--accent); }
```

Sem borda lateral grossa colorida em cartão (`side-tab` — pego pelo hook do
impeccable no mockup, ver nota abaixo); destaque de vencedor/estado ativo usa
`box-shadow` suave (glow) ou fundo levemente diferente, nunca uma borda de 3-4px
numa lateral só.

`refs.html` não importa esse CSS — continua com a paleta `color-scheme: light
dark` atual.

**Nota do mockup**: o hook de design do impeccable sinalizou a borda lateral
dourada da opção "C" do companion (`side-tab`, tell reconhecível de UI gerada
por IA). Aceito o apontamento — a versão final usa glow/sombra em vez de
borda lateral, como já registrado acima.

## 2. Animação de contador

`web/score-animation.js` (compartilhado, mesmo `<script src>` nos dois
arquivos):

```js
// anima um <b> de 0 ate valorFinal com desaceleracao (ease-out), tipo caca-niquel.
// duracao escala com o valor (max 800ms, pra 100 pontos) — uma nota de 20
// nao fica com o mesmo suspense de uma nota de 100.
function animaContador(el, valorFinal, duracaoMaxMs = 800) {
  const duracaoMs = Math.max(150, (Math.abs(valorFinal) / 100) * duracaoMaxMs);
  const inicio = performance.now();
  function passo(agora) {
    const t = Math.min(1, (agora - inicio) / duracaoMs);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = (valorFinal * eased).toFixed(1);
    if (t < 1) requestAnimationFrame(passo);
    else el.textContent = valorFinal.toFixed(1);
  }
  requestAnimationFrame(passo);
}
```

Chamada em todo lugar que hoje faz `elemento.textContent = data.total` (ou
`melody`/`rhythm`/`attacks`):

- `mimic.html`: os 4 números da resposta de `/api/score`.
- `party.html`: total do jogador no resumo da rodada; totais da tabela final
  quando ela aparece (nota de placar final pode passar de 100 somando
  rodadas — `duracaoMaxMs` nesse caso escala em cima do maior total da
  tabela, não de um teto fixo de 100, senão placares altos sempre bateriam
  no teto e pareceriam iguais).
- Piso de 150ms pra nota 0 não ficar instantânea/sem feedback nenhum.

## 3. Efeitos sonoros

Dois arquivos em `web/sfx/` (asset fixo do app, não gerenciável via
`refs.html` — isso é UI, não conteúdo de jogo):

- `ding.mp3` — toca quando `animaContador` começa, em `mimic.html` e
  `party.html`.
- `aplauso.mp3` — toca só quando a tela final do jogo de festa aparece.

`scripts/fetch_ui_sfx.py`, novo, baixa os dois do MyInstants reaproveitando
os headers já resolvidos em `scripts/fetch_mimic_refs.py` (User-Agent +
Referer + Accept + Range — o 403 do CDN cai com eles). Diferença chave: SEM a
lógica de curadoria (`MIN_ATAQUES`/`MIN_DUR_S`) — esses sons não são
pontuados, só tocados, então não precisam do scorer pra validar. Mantém em
mp3 (não converte pra wav 16k mono) — é playback puro, sem motivo pra pagar o
ffmpeg.

IDs exatos do MyInstants (arquivo/URL) ficam pra fase de implementação —
pesquisa de qual clipe usar cabe ao executor, com a mesma régua de qualidade
usada nos 10 clipes do `mimic_refs` (curto, reconhecível, sem ruído de fundo).

Toque via `new Audio("/static/sfx/ding.mp3").play()` — sem framework de
áudio, é o que o navegador já dá de graça.

## 4. Transições

Troca de `hidden` (`party.html`) e das seções de estado (`mimic.html`) ganha
um crossfade de ~200ms: uma classe `.fading` com `opacity:0` e
`transition: opacity 200ms`, aplicada um tick antes de trocar o `hidden` via
`requestAnimationFrame`/`setTimeout(200)`. Sem biblioteca de animação — é CSS
transition padrão.

## Testes / verificação

Sem framework de teste JS no repo (decisão já tomada nas telas anteriores,
`party.html`/`refs.html` foram verificadas manualmente no browser, não por
teste automatizado). Este refresh segue o mesmo padrão:

- Verificação manual no browser: tema aplicado, contador anima e para no
  valor certo, sons tocam nos momentos certos, crossfade sem flash/salto.
- `scripts/fetch_ui_sfx.py` sem teste pytest — mesmo padrão do
  `fetch_mimic_refs.py` (que também não tem).
- Nenhuma rota nova de backend nesta spec — logo nenhum teste de
  `server_*_addendum.py` novo é esperado. Se a implementação precisar de
  rota nova (não deveria — sons são estáticos, servidos pelo
  `static_folder="web"` já existente), volta pro plano antes de escrever.

## Riscos

1. Licenciamento do MyInstants pros 2 SFX é tão informal quanto o dos 10
   clipes de `mimic_refs` já aceitos no projeto — mesmo risco já assumido,
   não é novo aqui.
2. CSS compartilhado (`theme-karaoke.css`) é a primeira folha de estilo
   entre arquivos neste projeto — se um terceiro arquivo precisar do mesmo
   tema no futuro, reusa; se só ficar nesses 2, o custo de manutenção é
   baixo (é ~20 linhas de tokens).
