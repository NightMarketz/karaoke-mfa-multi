// mic-meter.js — indicador de nivel do mic em tempo real, so visual. NAO mede nada
// que o scorer usa (aquilo roda depois, no servidor, sobre o WAV inteiro) — e'
// feedback pro jogador saber "o mic esta me captando", nao previa da nota.
//
// Uso: const m = criaMedidor(stream, barrasEl); ... m.para() ao parar de gravar.
function criaMedidor(stream, barrasEl) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const fonte = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  fonte.connect(analyser);
  const dados = new Uint8Array(analyser.fftSize);
  const barras = [...barrasEl.children];
  let ativo = true;

  function passo() {
    if (!ativo) return;
    analyser.getByteTimeDomainData(dados);
    let soma = 0;
    for (let i = 0; i < dados.length; i++) {
      const v = (dados[i] - 128) / 128;
      soma += v * v;
    }
    const rms = Math.sqrt(soma / dados.length);
    // fala normal da um RMS baixo (~0.02-0.15) — escala nao-linear pra encher a
    // barra em volume de conversa, nao so em grito.
    const nivel = Math.min(1, rms * 6);
    const ativas = Math.round(nivel * barras.length);
    barras.forEach((b, i) => b.classList.toggle("ativa", i < ativas));
    requestAnimationFrame(passo);
  }
  requestAnimationFrame(passo);

  return {
    para() {
      ativo = false;
      barras.forEach((b) => b.classList.remove("ativa"));
      fonte.disconnect();
      ctx.close().catch(() => {});
    },
  };
}
