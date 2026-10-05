// audio-player.js — player customizado mínimo pro <audio> de referência.
// O <audio controls> nativo não pega o tema (cada browser desenha os controles
// nativos do jeito dele, sem CSS hook confiável) — troca por botão + barra
// próprios, controlando o <audio> escondido por baixo.
//
// Uso: const p = criaPlayer(audioEl, botaoEl, barraEl); p.recarrega() depois de
// trocar audioEl.src (o botão volta pro estado "tocar" e a barra zera).
function criaPlayer(audio, botao, barra) {
  const iconePlay = botao.querySelector("use");

  function assinaIcone(nome) { iconePlay.setAttribute("href", "#icon-" + nome); }

  botao.addEventListener("click", () => {
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  });
  audio.addEventListener("play", () => assinaIcone("pause"));
  audio.addEventListener("pause", () => assinaIcone("play"));
  audio.addEventListener("ended", () => assinaIcone("play"));
  audio.addEventListener("timeupdate", () => {
    // fracao 0..1, nao percentual: a barra usa transform: scaleX() (so compositor,
    // sem reflow a cada frame) em vez de width.
    const frac = audio.duration ? audio.currentTime / audio.duration : 0;
    barra.style.setProperty("--progresso", frac);
  });
  audio.addEventListener("error", () => { botao.disabled = true; });

  return {
    recarrega() {
      botao.disabled = false;
      assinaIcone("play");
      barra.style.setProperty("--progresso", 0);
    },
  };
}
