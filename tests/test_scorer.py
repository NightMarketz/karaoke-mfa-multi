import numpy as np
import pytest

from karaoke.audio_fixtures import SR, bursts
from karaoke.scorer import MIN_VOICED_FRAMES, track_from_audio

TIMES = [0.3, 0.9, 1.5, 2.4, 3.0]
FREQS = [220.0, 247.0, 262.0, 294.0, 330.0]


def test_track_extrai_ataques_e_contorno():
    track = track_from_audio(bursts(TIMES, FREQS), SR)

    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} esperados"
    )
    # cardinalidade: contorno vazio e FALHA, nao sucesso
    assert track.n_voiced >= MIN_VOICED_FRAMES, (
        f"apenas {track.n_voiced} frames voiced de {track.n_frames} — populacao insuficiente"
    )
    assert track.n_voiced <= track.n_frames, "voiced nao pode exceder o total de frames"
    assert len(track.semitones) == track.n_voiced
    # duration e do recorte por voz (emenda 3); recorte + pontas removidas = entrada
    assert track.duration + track.trim_start_s + track.trim_end_s == pytest.approx(
        len(bursts(TIMES, FREQS)) / SR, abs=0.01
    )
    assert track.trim_start_s > 0.0, "fixture tem 0,3 s de silencio antes: algo tinha que sair"


def test_contorno_centrado_na_mediana():
    """Mediana em zero e o que torna a nota agnostica a registro."""
    track = track_from_audio(bursts(TIMES, FREQS), SR)
    assert float(np.median(track.semitones)) == pytest.approx(0.0, abs=0.5)


def test_transposicao_nao_muda_o_contorno():
    base = track_from_audio(bursts(TIMES, FREQS), SR)
    alto = track_from_audio(bursts(TIMES, [f * 2 ** (5 / 12) for f in FREQS]), SR)

    n = min(len(base.semitones), len(alto.semitones))
    assert n >= MIN_VOICED_FRAMES, f"apenas {n} frames comparaveis"
    diff = float(np.mean(np.abs(base.semitones[:n] - alto.semitones[:n])))
    assert diff <= 1.0, f"contorno mudou {diff:.2f} semitons com transposicao de +5"


def test_conta_suspeita_de_erro_de_oitava():
    """Risco 2 do spec vira numero, nao promessa. Bursts limpos nao devem ter salto
    de oitava; o contador existe para o material real, onde e 4.9%."""
    track = track_from_audio(bursts(TIMES, FREQS), SR)
    assert track.n_voiced >= MIN_VOICED_FRAMES, f"{track.n_voiced} frames voiced"
    frac = track.n_octave_suspect / track.n_voiced
    assert frac <= 0.05, (
        f"{track.n_octave_suspect} de {track.n_voiced} frames com salto de oitava "
        f"({100 * frac:.1f}%) em fixture sintetica limpa"
    )


def test_ganho_baixo_nao_perde_ataques():
    """Os limiares do detector sao absolutos; sem normalizar por pico, esta fixture a
    -30dB (pico ~0.019, abaixo de ENERGY_MIN=0.02) da ZERO ataques. Medido em 2026-09-11:
    0 de 5 sem normalizar, 5 de 5 com. E o mesmo fenomeno que deu 39 vs 163 no
    material real."""
    baixo = bursts(TIMES, FREQS) * 10 ** (-30 / 20)
    assert float(np.abs(baixo).max()) < 0.02, "fixture nao ficou abaixo de ENERGY_MIN"
    track = track_from_audio(baixo, SR)
    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} com ganho a -30dB"
    )


def test_silencio_nao_produz_contorno():
    """Controle negativo: audio mudo da populacao vazia, e isso deve ser visivel."""
    track = track_from_audio(np.zeros(int(2.0 * SR), dtype=np.float32), SR)
    assert len(track.onsets) == 0
    assert track.n_voiced < MIN_VOICED_FRAMES, (
        f"silencio gerou {track.n_voiced} frames voiced"
    )
    assert track.n_octave_suspect == 0
    assert (track.trim_start_s, track.trim_end_s) == (0.0, 0.0), (
        f"silencio absoluto foi recortado: ({track.trim_start_s}, {track.trim_end_s})"
    )


from karaoke.scorer import score

DIFERENTE_TIMES = [0.2, 1.7, 2.9]
DIFERENTE_FREQS = [440.0, 330.0, 392.0]
EMBARALHADO_TIMES = [0.3, 0.75, 1.9, 2.1, 3.1]
EMBARALHADO_FREQS = [FREQS[i] for i in (2, 0, 4, 1, 3)]


@pytest.fixture(scope="module")
def ref():
    return track_from_audio(bursts(TIMES, FREQS), SR)


def _total(ref_track, times, freqs):
    return score(ref_track, track_from_audio(bursts(times, freqs), SR))


def _baseline_aleatorio(ref_track, n=30, seed=7):
    """p95 do acaso. Sem esta regua, nenhuma nota alta significa nada."""
    rng = np.random.default_rng(seed)
    totais = []
    for _ in range(n):
        k = int(rng.integers(3, 7))
        t = np.sort(rng.uniform(0.2, 3.2, k)).tolist()
        f = rng.uniform(150.0, 500.0, k).tolist()
        totais.append(_total(ref_track, t, f).total)
    return np.asarray(totais)


# ── controle 1: identidade ───────────────────────────────────────────────────
def test_controle_1_identidade(ref):
    r = _total(ref, TIMES, FREQS)
    assert r.n_frames_compared > 0, "zero frames comparados e falha, nao sucesso"
    assert r.n_onsets_ref == r.n_onsets_take == len(TIMES)
    assert r.total >= 95.0, f"identidade deu {r.total:.1f} (esperado >= 95)"


# ── controle 4: transposto ───────────────────────────────────────────────────
def test_controle_4_transposto_mantem_melodia(ref):
    r = _total(ref, TIMES, [f * 2 ** (5 / 12) for f in FREQS])
    assert r.n_frames_compared > 0
    assert r.melody >= 85.0, f"melodia caiu para {r.melody:.1f} com +5 semitons"


# ── controle 3: embaralhado ──────────────────────────────────────────────────
def test_controle_3_embaralhado_derruba_ritmo(ref):
    r = _total(ref, EMBARALHADO_TIMES, EMBARALHADO_FREQS)
    ident = _total(ref, TIMES, FREQS)
    assert r.rhythm < 50.0, f"ritmo {r.rhythm:.1f} alto para take embaralhado"
    assert r.total < ident.total, (
        f"embaralhado ({r.total:.1f}) nao ficou abaixo da identidade ({ident.total:.1f})"
    )


# ── controle 2: clipe diferente ──────────────────────────────────────────────
def test_controle_2_clipe_diferente(ref):
    dif = _total(ref, DIFERENTE_TIMES, DIFERENTE_FREQS)
    emb = _total(ref, EMBARALHADO_TIMES, EMBARALHADO_FREQS)
    assert dif.total < emb.total, (
        f"clipe diferente ({dif.total:.1f}) deveria ficar abaixo do embaralhado ({emb.total:.1f})"
    )


# ── controle 5: baseline aleatorio e as relacoes exigidas ────────────────────
def test_controle_5_identidade_supera_o_acaso(ref):
    totais = _baseline_aleatorio(ref)
    assert len(totais) == 30, f"baseline examinou {len(totais)} amostras de 30"
    p95 = float(np.percentile(totais, 95))
    ident = _total(ref, TIMES, FREQS).total
    assert ident > p95, (
        f"identidade {ident:.1f} nao supera o p95 do acaso {p95:.1f} "
        f"(media do acaso {totais.mean():.1f})"
    )


def test_relacoes_de_ordem_completas(ref):
    """As tres relacoes inegociaveis do spec, num teste so, com os numeros a vista."""
    ident = _total(ref, TIMES, FREQS).total
    transp = _total(ref, TIMES, [f * 2 ** (5 / 12) for f in FREQS]).total
    emb = _total(ref, EMBARALHADO_TIMES, EMBARALHADO_FREQS).total
    dif = _total(ref, DIFERENTE_TIMES, DIFERENTE_FREQS).total
    p95 = float(np.percentile(_baseline_aleatorio(ref), 95))

    assert abs(ident - transp) <= 5.0, f"identidade {ident:.1f} vs transposto {transp:.1f}"
    assert ident > emb > dif, f"ordem quebrou: {ident:.1f} > {emb:.1f} > {dif:.1f}"
    assert ident > p95, f"identidade {ident:.1f} nao supera acaso p95 {p95:.1f}"
    assert dif < p95, f"clipe diferente {dif:.1f} nao ficou abaixo do acaso p95 {p95:.1f}"


def test_ritmo_esticado_fica_abaixo_do_acaso(ref):
    """Take a 1.3x do andamento: a deriva estoura MATCH_TOL_S e o F1 cai ao nivel do
    acaso — sem termo de andamento (spec, emenda 2026-09-12 (2): medido 40 contra p95
    do acaso 64). Antes, com tolerancia relativa 0.21s, o conjunto casava quase tudo."""
    esticado = _total(ref, [t * 1.3 for t in TIMES], FREQS)
    assert esticado.n_onsets_take == len(TIMES), (
        f"{esticado.n_onsets_take} ataques de {len(TIMES)} no take esticado"
    )
    assert esticado.rhythm < 50.0, (
        f"take esticado 1.3x recebeu rhythm {esticado.rhythm:.1f} "
        f"({esticado.n_matched} de {esticado.n_onsets_ref} casados)"
    )


def test_onset_espurio_antes_nao_derruba_abaixo_do_acaso(ref):
    """O clique do botao ou uma respiracao antes da primeira nota e o take NORMAL.
    Medido em 2026-09-11: com truncamento posicional dava total 45.9 < p95 49.5;
    com casamento por conjunto da rhythm 90.9 (precisao 5 de 6) e total > p95 do acaso."""
    espurio = _total(ref, [0.1] + TIMES, [300.0] + FREQS)
    assert espurio.n_onsets_take == len(TIMES) + 1, (
        f"{espurio.n_onsets_take} ataques de {len(TIMES) + 1} esperados"
    )
    assert espurio.rhythm >= 85.0, (
        f"rhythm {espurio.rhythm:.1f} com um onset espurio antes "
        f"({espurio.n_matched} de {espurio.n_onsets_ref} casados, precisao 5/6 esperada)"
    )
    p95 = float(np.percentile(_baseline_aleatorio(ref), 95))
    assert espurio.total > p95, (
        f"take perfeito com onset espurio antes ({espurio.total:.1f}) "
        f"nao supera o p95 do acaso ({p95:.1f})"
    )


def test_take_sem_ataque_suficiente_nao_inventa_nota(ref):
    """Controle negativo: take mudo tem que dar nota baixa com denominador visivel."""
    r = score(ref, track_from_audio(np.zeros(int(2.0 * SR), dtype=np.float32), SR))
    assert r.n_onsets_take == 0, f"silencio gerou {r.n_onsets_take} ataques"
    assert r.n_frames_compared == 0, "sem contorno nao ha frames comparados"
    assert r.rhythm == 0.0 and r.melody == 0.0
    assert r.total < 25.0, f"take mudo recebeu {r.total:.1f}"


from karaoke.scorer import WINDOW_PAD_S, track_from_word_timing


def test_karaoke_ataques_vem_do_audio_dentro_da_janela():
    """Os ataques vem do DETECTOR sobre o recorte do gabarito, nao dos inicios de
    palavra. Mesma populacao que o take: e o que faz attacks e rhythm compararem
    igual com igual (spec, emenda 2026-09-12)."""
    words = [
        {"word": "um", "start": 0.30, "end": 0.55, "score": 1.0},
        {"word": "dois", "start": 0.90, "end": 1.15, "score": 1.0},
        {"word": "tres", "start": 1.50, "end": 1.75, "score": 1.0},
        {"word": "quatro", "start": 2.40, "end": 2.65, "score": 1.0},
        {"word": "cinco", "start": 3.00, "end": 3.25, "score": 1.0},
    ]
    audio = bursts(TIMES, FREQS)
    track = track_from_word_timing(words, audio, SR)
    direto = track_from_audio(audio, SR)

    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} bursts na janela"
    )
    # mesmos intervalos que o detector acha no audio inteiro: a janela so desloca
    np.testing.assert_allclose(np.diff(track.onsets), np.diff(direto.onsets), atol=0.02)
    # onsets sao relativos ao inicio da janela: o primeiro cai a ~WINDOW_PAD_S
    assert abs(track.onsets[0] - WINDOW_PAD_S) <= 0.05, (
        f"primeiro ataque em {track.onsets[0]:.3f}s, esperado ~{WINDOW_PAD_S}s"
    )
    assert track.n_voiced >= MIN_VOICED_FRAMES, (
        f"{track.n_voiced} frames voiced de {track.n_frames}"
    )


def test_karaoke_gabarito_vazio_e_erro_nao_nota_zero():
    """Populacao vazia tem que explodir, nao virar nota. Zero itens nao e sucesso."""
    with pytest.raises(ValueError, match="vazio"):
        track_from_word_timing([], bursts(TIMES, FREQS), SR)


def test_karaoke_gabarito_fora_de_ordem_e_erro():
    words = [
        {"word": "um", "start": 1.00, "end": 1.20, "score": 1.0},
        {"word": "dois", "start": 0.50, "end": 0.70, "score": 1.0},
    ]
    with pytest.raises(ValueError, match="monot"):
        track_from_word_timing(words, bursts(TIMES, FREQS), SR)


def test_karaoke_pontua_contra_si_mesmo():
    """O take que reproduz o gabarito recebe nota alta — mesmo score() dos dois modos."""
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]
    audio = bursts(TIMES, FREQS)
    ref = track_from_word_timing(words, audio, SR)
    r = score(ref, track_from_audio(audio, SR))
    assert r.n_frames_compared > 0
    # piso de sanidade, nao cerca de regressao: a versao antiga tambem dava 100 nesta
    # fixture (a cerca da mudanca e onsets[0] ~ WINDOW_PAD_S no teste da janela)
    assert r.total >= 95.0, f"karaoke contra si mesmo deu {r.total:.1f}"


def test_karaoke_janela_exclui_ataque_fora_do_gabarito():
    """Um burst 3s depois da ultima palavra existe no audio mas NAO na referencia.
    Controle: o detector sobre o audio inteiro acha 6 — a janela e quem tira 1."""
    times = TIMES + [6.0]
    freqs = FREQS + [262.0]
    audio = bursts(times, freqs)
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]        # so as 5 primeiras: 6.0 fica de fora

    inteiro = track_from_audio(audio, SR)
    assert len(inteiro.onsets) == 6, (
        f"controle: detector achou {len(inteiro.onsets)} de 6 bursts no audio inteiro"
    )
    ref = track_from_word_timing(words, audio, SR)
    assert len(ref.onsets) == 5, (
        f"janela deixou passar {len(ref.onsets)} ataques de 5 palavras"
    )


def test_karaoke_folga_captura_o_primeiro_ataque(monkeypatch):
    """Recorte que comeca EM CIMA do primeiro burst nao ve o RMS subir e perde o
    ataque. Sabotagem: WINDOW_PAD_S = 0 tem que ficar vermelho (re-derivado em
    2026-09-12 nesta fixture: pad 0 pega 4 de 5)."""
    import karaoke.scorer as mod
    words = [{"word": f"w{i}", "start": t, "end": t + 0.25, "score": 1.0}
             for i, t in enumerate(TIMES)]
    audio = bursts(TIMES, FREQS)

    com_folga = track_from_word_timing(words, audio, SR)
    assert len(com_folga.onsets) == len(TIMES), (
        f"com folga: {len(com_folga.onsets)} de {len(TIMES)}"
    )

    monkeypatch.setattr(mod, "WINDOW_PAD_S", 0.0)
    sem_folga = track_from_word_timing(words, audio, SR)
    assert len(sem_folga.onsets) < len(TIMES), (
        f"controle negativo nao ficou vermelho: pad 0 ainda pegou "
        f"{len(sem_folga.onsets)} de {len(TIMES)} — a folga nao esta sendo testada"
    )


def test_karaoke_gabarito_sem_end_ou_janela_vazia_e_erro():
    audio = bursts(TIMES, FREQS)
    with pytest.raises(ValueError, match="end"):
        track_from_word_timing([{"word": "um", "start": 0.3, "score": 1.0}], audio, SR)
    # gabarito inteiro depois do fim do audio: janela recortada ao audio fica vazia
    fora = [{"word": "um", "start": 50.0, "end": 50.3, "score": 1.0}]
    with pytest.raises(ValueError, match="janela"):
        track_from_word_timing(fora, audio, SR)


def test_ritmo_jitter_humano_nao_custa(ref):
    """Cantar no tempo com +-40ms de jitter e o take BOM. Posicional dava 62;
    casamento com MATCH_TOL_S = 0.08 tem que dar ~100."""
    jitter = [0.04, -0.04, 0.04, -0.04, 0.04]
    r = _total(ref, [t + j for t, j in zip(TIMES, jitter)], FREQS)
    assert r.n_matched == len(TIMES), f"{r.n_matched} de {len(TIMES)} casados"
    assert r.rhythm >= 95.0, f"jitter de 40ms custou rhythm {r.rhythm:.1f}"


def test_ritmo_take_denso_paga_em_precisao(ref):
    """So recall e enganavel: um take com os 5 ataques certos MAIS 10 espurios casa
    100% da referencia. A precisao (5 de 15) e o que derruba. Controle: o recall
    sozinho seria 1.0 — visivel em n_matched == n_onsets_ref."""
    extras = [0.5, 0.7, 1.1, 1.3, 1.7, 2.0, 2.2, 2.6, 2.8, 3.2]
    times = sorted(TIMES + extras)
    freqs = FREQS + [300.0] * len(extras)
    denso = _total(ref, times, freqs)
    assert denso.n_onsets_take == 15, f"{denso.n_onsets_take} ataques de 15 no take denso"
    assert denso.n_matched == len(TIMES), (
        f"controle: recall deveria ser cheio, casou {denso.n_matched} de {len(TIMES)}"
    )
    assert denso.rhythm < 60.0, (
        f"take denso recebeu rhythm {denso.rhythm:.1f} com precisao "
        f"{denso.n_matched}/{denso.n_onsets_take}"
    )


def test_ritmo_deslocamento_global_e_estimado_nao_assumido(ref):
    """Um deslocamento global de 0.45s entre os trens de ataque custa zero: o
    offset vem da correlacao cruzada. Controle negativo: sem alinhar (b=0) o
    casamento a 0.08s nao acha nada — 0.45 e escolhido para que o par nao
    alinhado mais proximo fique a 0.15s (0.9 vs 0.75), longe da tolerancia.
    Testado no nivel dos ataques: pre-roll de SILENCIO no audio e removido pelo
    recorte por voz (emenda 3) antes de chegar aqui; o fim-a-fim com coisa antes
    que o recorte nao tira (uma nota) e test_onset_espurio_antes_nao_derruba_abaixo_do_acaso."""
    from karaoke.scorer import _align_offset, _match_f1, MATCH_TOL_S
    deslocado = ref.onsets + 0.45
    b = _align_offset(ref.onsets, deslocado)
    assert abs(b - 0.45) <= MATCH_TOL_S, f"offset estimado {b:.3f}s, esperado 0.45s"
    f1_sem, n_sem = _match_f1(ref.onsets, deslocado)
    assert n_sem == 0, f"controle: sem alinhar casou {n_sem} de {len(TIMES)}"
    f1_com, n_com = _match_f1(ref.onsets, deslocado - b)
    assert n_com == len(TIMES), f"{n_com} de {len(TIMES)} casados depois de alinhar"
    assert f1_com >= 0.95, f"deslocamento de 0.45s custou F1 {f1_com:.2f}"


# ── emenda 3: recorte por atividade de voz ──────────────────────────────────
from karaoke.onset import compute_rms, detect_onsets


def test_clique_no_inicio_nao_afoga_o_vocal():
    """Clique de botao (5 ms a 1,0) antes de um vocal a 0,02 de pico. Normalizado
    pelo pico do CLIQUE, o vocal cai abaixo de ENERGY_MIN e o detector perde os
    ataques — no job real 40 de 164 sobrevivem, rhythm 38,2 (medido 2026-09-12).
    O recorte por voz tira o clique ANTES da normalizacao."""
    vocal = bursts(TIMES, FREQS) * (0.02 / 0.6)
    take = np.concatenate([np.zeros(int(0.5 * SR), dtype=np.float32), vocal])
    take[int(0.05 * SR):int(0.055 * SR)] = 1.0

    # controle negativo: sem o recorte, normalizar pelo clique afoga o vocal
    rms, fd = compute_rms(take / float(np.abs(take).max()), SR)
    sem_recorte = len(detect_onsets(rms, fd))
    assert sem_recorte < len(TIMES), (
        f"controle: sem recorte o detector ainda acha {sem_recorte} de {len(TIMES)} — "
        "a sabotagem nao sabotou, o teste nao prova nada"
    )

    track = track_from_audio(take, SR)
    assert track.trim_start_s > 0.055, (
        f"recorte comecou em {track.trim_start_s:.3f}s: o clique (0,050-0,055 s) ficou dentro"
    )
    assert len(track.onsets) == len(TIMES), (
        f"{len(track.onsets)} ataques de {len(TIMES)} com clique antes (sem recorte: {sem_recorte})"
    )


def test_clique_colado_na_primeira_nota_tambem_sai():
    """Clique 150 ms antes da primeira nota — mais perto que VOICE_MIN_SILENCE_MS
    (200 ms) e mais longe que o alcance do pad (VOICE_PAD_MS + janela de RMS,
    ~125 ms). Com gap-fill antes de spike-removal o clique era fundido a voz
    (medido: 1 de 5 ataques a 150 ms de gap)."""
    vocal = bursts(TIMES, FREQS) * (0.02 / 0.6)          # primeira nota em TIMES[0] = 0,3 s
    take = vocal.copy()
    i = int((TIMES[0] - 0.150) * SR)
    take[i:i + int(0.005 * SR)] = 1.0
    track = track_from_audio(take, SR)
    assert track.trim_start_s > (TIMES[0] - 0.150) + 0.005, (
        f"recorte comecou em {track.trim_start_s:.3f}s: clique a 150 ms da nota ficou dentro"
    )
    assert len(track.onsets) == len(TIMES), f"{len(track.onsets)} ataques de {len(TIMES)}"


def test_recorte_tira_silencio_das_duas_pontas_e_desloca_os_ataques():
    """1 s de silencio antes e 1 s depois: os dois somem, os ataques ficam relativos
    ao recorte (o primeiro cai a ~VOICE_PAD_MS do inicio) e os intervalos nao mudam."""
    from karaoke.scorer import VOICE_PAD_MS
    base = bursts(TIMES, FREQS)
    take = np.concatenate([np.zeros(SR, dtype=np.float32), base, np.zeros(SR, dtype=np.float32)])
    track = track_from_audio(take, SR)
    direto = track_from_audio(base, SR)

    esperado_inicio = 1.0 + TIMES[0] - VOICE_PAD_MS / 1000
    assert abs(track.trim_start_s - esperado_inicio) <= 0.05, (
        f"trim_start_s {track.trim_start_s:.3f}s, esperado ~{esperado_inicio:.2f}s"
    )
    assert track.trim_end_s >= 0.9, f"trim_end_s {track.trim_end_s:.3f}s: o silencio do fim ficou"
    assert len(track.onsets) == len(TIMES), f"{len(track.onsets)} ataques de {len(TIMES)}"
    assert abs(track.onsets[0] - VOICE_PAD_MS / 1000) <= 0.05, (
        f"primeiro ataque em {track.onsets[0]:.3f}s, esperado ~{VOICE_PAD_MS / 1000}s"
    )
    np.testing.assert_allclose(np.diff(track.onsets), np.diff(direto.onsets), atol=0.02)
