// letra-trecho.js — letra de um trecho com preenchimento palavra a palavra, em
// sincronia com o currentTime de um <audio>. Mesma regra de preenchimento do
// karaoke-player.js (_updateHighlight). Tempos dos versos/palavras sao ABSOLUTOS
// na musica (o audio toca a base inteira, posicionado no inicio do trecho).
//
// Uso: const l = criaLetraTrecho(containerEl, trecho.versos, audio); ... l.para()
function criaLetraTrecho(container, versos, audio) {
  container.textContent = "";
  const itens = versos.map((v) => {
    const el = document.createElement("div");
    el.className = "verso futuro";
    const palavras = (v.palavras || []).map((p) => {
      const sp = document.createElement("span");
      sp.className = "palavra";
      sp.dataset.p = "";
      sp.textContent = p.texto;
      sp.dataset.t = p.texto; // camada de preenchimento (::after) le daqui
      sp.style.setProperty("--fill", "0");
      el.appendChild(sp);
      el.appendChild(document.createTextNode(" "));
      return { el: sp, inicio: p.inicio, fim: p.fim, fill: 0 };
    });
    container.appendChild(el);
    return { el, inicio: v.inicio, fim: v.fim, estado: "futuro", palavras };
  });

  let ativo = true;
  let idxAtivo = -1;

  // Rola SO o container (scrollIntoView rolaria tambem a pagina quando a secao e'
  // mais alta que a tela). Posicao relativa via getBoundingClientRect: nao depende
  // do offsetParent do verso.
  function centraNoContainer(el) {
    const rc = container.getBoundingClientRect();
    const re = el.getBoundingClientRect();
    const alvo = container.scrollTop + (re.top - rc.top) - (container.clientHeight - re.height) / 2;
    const max = Math.max(0, container.scrollHeight - container.clientHeight);
    container.scrollTo({ top: Math.min(max, Math.max(0, alvo)), behavior: "smooth" });
  }

  function passo() {
    if (!ativo) return;
    const t = audio.currentTime;
    let novoAtivo = -1;
    itens.forEach((v, i) => {
      const estado = t >= v.fim ? "passado" : t >= v.inicio ? "ativo" : "futuro";
      if (estado === "ativo") novoAtivo = i;
      if (estado !== v.estado) {
        v.estado = estado;
        v.el.className = "verso " + estado;
      }
      for (const p of v.palavras) {
        const d = p.fim - p.inicio;
        const f = d > 0.001 ? Math.min(1, Math.max(0, (t - p.inicio) / d)) : t >= p.inicio ? 1 : 0;
        if (f !== p.fill) {
          p.fill = f;
          p.el.style.setProperty("--fill", String(f));
        }
      }
    });
    if (novoAtivo !== idxAtivo) {
      idxAtivo = novoAtivo;
      if (novoAtivo >= 0) centraNoContainer(itens[novoAtivo].el);
    }
    requestAnimationFrame(passo);
  }
  requestAnimationFrame(passo);

  return {
    para() {
      ativo = false;
      container.textContent = "";
    },
  };
}
