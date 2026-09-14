// score-animation.js — compartilhado por party.html e mimic.html.

// Anima um <b> de 0 ate valorFinal com desaceleracao (ease-out), tipo caca-niquel.
// Duracao escala com o valor (max duracaoMaxMs, pra um valor igual a escalaMax) — uma
// nota de 20 nao fica com o mesmo suspense de uma nota de 100. Piso de 150ms pra um
// valor 0 nao ficar instantaneo/sem feedback nenhum.
// escalaMax existe pro placar final do jogo de festa: ali o total pode passar de 100
// somando rodadas, entao quem chama passa o MAIOR total da tabela como escalaMax — senao
// todo placar alto bateria no teto de 800ms e pareceria igual.
function animaContador(el, valorFinal, duracaoMaxMs = 800, escalaMax = 100) {
  const duracaoMs = Math.max(150, (Math.abs(valorFinal) / escalaMax) * duracaoMaxMs);
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

// Crossfade de ~200ms entre telas/estados: aplica opacity:0 (classe .fading, ver
// theme-karaoke.css) um tick antes de trocar o hidden, e some so depois que a
// transicao terminou — sem flash nem salto. elOcultar pode ser null (soh fade-in,
// caso do mimic.html: nao ha outra secao pra esconder junto).
function crossfade(elOcultar, elMostrar) {
  function troca() {
    if (elOcultar) elOcultar.hidden = true;
    if (elMostrar) {
      elMostrar.hidden = false;
      elMostrar.classList.add("fading");
      requestAnimationFrame(() => elMostrar.classList.remove("fading"));
    }
  }
  if (elOcultar) {
    elOcultar.classList.add("fading");
    setTimeout(troca, 200);
  } else {
    troca();
  }
}
