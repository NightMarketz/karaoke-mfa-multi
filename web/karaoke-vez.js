// karaoke-vez.js — modo Karaoke do jogo de festa (party.html): fila de trechos da
// partida e a "vez" de um jogador (contagem, base instrumental + letra, gravacao que
// para sozinha no fim do trecho). Depende de criaLetraTrecho (letra-trecho.js) e
// criaMedidor (mic-meter.js), carregados antes deste arquivo.

const PRE_ROLL_S = 2;   // a base entra 2 s antes do primeiro verso (servidor: MAX_TAKE_S cobre isso)
const CONTAGEM_S = 3;   // 3-2-1 antes de cantar

// porMusica: [{musica: {id, titulo}, trechos: [...]}] -> [{job, titulo, inicio, fim, versos}]
// Descarta trechos `longo` e intercala as musicas, um trecho de cada por vez, na
// ordem que cada lista ja traz (refrao primeiro). Nao embaralha.
function montaFilaDeTrechos(porMusica) {
  const listas = porMusica.map(({ musica, trechos }) =>
    (trechos || [])
      .filter((t) => !t.longo)
      .map((t) => ({ job: musica.id, titulo: musica.titulo, inicio: t.inicio, fim: t.fim, versos: t.versos })));
  const fila = [];
  const maior = Math.max(0, ...listas.map((l) => l.length));
  for (let i = 0; i < maior; i++) {
    for (const l of listas) if (i < l.length) fila.push(l[i]);
  }
  return fila;
}

// Uma vez de cantar. `stream` e' de quem chama (ele solta o mic em aoTerminar/aoErro);
// o resto (contagem, base, letra, medidor, gravador) e' parado aqui dentro antes de
// qualquer callback, e por cancela(). aoErro(msg) e' opcional: sem ele a mensagem vai
// pro estadoEl.
function vezKaraoke({ trecho, audio, letraEl, medidorEl, estadoEl, stream, aoTerminar, aoErro }) {
  let encerrada = false;   // terminou, falhou ou foi cancelada: nada mais roda
  let cancelada = false;   // rec.onstop nao entrega blob
  let timer = null, raf = 0, rec = null, chunks = [];
  const inicioBase = Math.max(0, trecho.inicio - PRE_ROLL_S);

  const medidor = criaMedidor(stream, medidorEl);
  medidorEl.hidden = false;

  let okMeta, erroMeta;
  const metadata = new Promise((res, rej) => { okMeta = res; erroMeta = rej; });
  const aoMeta = () => okMeta();
  const aoErroAudio = () => erroMeta(new Error("falha ao carregar a base"));
  audio.addEventListener("loadedmetadata", aoMeta);
  audio.addEventListener("error", aoErroAudio);
  audio.pause();
  audio.preload = "auto";
  audio.src = "/api/karaoke/" + encodeURIComponent(trecho.job) + "/base";
  audio.load();
  metadata.then(() => { if (!encerrada) audio.currentTime = inicioBase; }, () => {});

  const letra = criaLetraTrecho(letraEl, trecho.versos, audio);

  function confere() {
    if (encerrada) return;
    if (audio.currentTime >= trecho.fim) termina();
  }
  function vigia() {
    if (encerrada) return;
    confere();
    raf = requestAnimationFrame(vigia);
  }

  function limpa() {
    if (timer) { clearInterval(timer); timer = null; }
    cancelAnimationFrame(raf);
    audio.pause();
    audio.removeEventListener("loadedmetadata", aoMeta);
    audio.removeEventListener("error", aoErroAudio);
    audio.removeEventListener("timeupdate", confere);
    audio.removeEventListener("ended", termina);
    letra.para();
    medidor.para();
    medidorEl.hidden = true;
  }
  function paraGravador() {
    if (rec && rec.state !== "inactive") rec.stop();
  }

  function termina() {
    if (encerrada) return;
    encerrada = true;
    limpa();
    paraGravador(); // onstop entrega o blob
  }
  function falha(msg) {
    if (encerrada) return;
    encerrada = true;
    cancelada = true;
    limpa();
    paraGravador();
    if (aoErro) aoErro(msg); else estadoEl.textContent = msg;
  }

  async function comeca() {
    if (encerrada) return;
    if (audio.readyState < 1) estadoEl.textContent = "Carregando a base…";
    try { await metadata; } catch (e) { return falha("Falha ao carregar a base instrumental."); }
    if (encerrada) return;
    audio.currentTime = inicioBase;
    try {
      rec = new MediaRecorder(stream);
    } catch (e) {
      return falha("Gravação não suportada neste navegador: " + e.name);
    }
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      if (cancelada) return;
      aoTerminar(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
    };
    try { await audio.play(); } catch (e) { return falha("Não deu para tocar a base: " + e.name); }
    if (encerrada) { audio.pause(); return; }
    rec.start();
    estadoEl.textContent = "Cante!";
    audio.addEventListener("timeupdate", confere); // rAF dorme em aba oculta; timeupdate nao
    audio.addEventListener("ended", termina);      // musica acabou antes do fim do trecho
    raf = requestAnimationFrame(vigia);
  }

  let n = CONTAGEM_S;
  estadoEl.textContent = String(n);
  timer = setInterval(() => {
    n--;
    if (n > 0) { estadoEl.textContent = String(n); return; }
    clearInterval(timer);
    timer = null;
    comeca();
  }, 1000);

  return {
    cancela() {
      if (encerrada) return;
      encerrada = true;
      cancelada = true;
      limpa();
      paraGravador();
    },
  };
}
