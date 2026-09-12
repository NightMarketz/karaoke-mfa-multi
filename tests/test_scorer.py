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
    assert track.duration == pytest.approx(len(bursts(TIMES, FREQS)) / SR, abs=0.01)


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


def test_ritmo_calibra_na_referencia_nao_no_take(ref):
    """A tolerancia de ritmo e derivada do intervalo mediano da REFERENCIA. Calibrar no
    take premiaria take esticado: medido em 2026-09-11, take a 1.3x da tempo tem
    rhythm 3.6 calibrando na referencia e 25.8 calibrando em si mesmo. O embaralhado
    nao distingue os dois (mad 0.45s satura em 0 de qualquer jeito) — por isso esta
    fixture existe."""
    esticado = _total(ref, [t * 1.3 for t in TIMES], FREQS)
    assert esticado.n_onsets_take == len(TIMES), (
        f"{esticado.n_onsets_take} ataques de {len(TIMES)} no take esticado"
    )
    assert esticado.rhythm < 15.0, (
        f"take esticado 1.3x recebeu rhythm {esticado.rhythm:.1f} "
        f"(tol {esticado.rhythm_tol_s:.3f}s) — calibracao esta no take, nao na referencia?"
    )


def test_onset_espurio_antes_nao_derruba_abaixo_do_acaso(ref):
    """O clique do botao ou uma respiracao antes da primeira nota e o take NORMAL.
    Medido em 2026-09-11: com truncamento posicional dava total 45.9 < p95 49.5;
    com tolerancia a um onset de borda da 80.9 (rhythm 100, attacks 83.3)."""
    espurio = _total(ref, [0.1] + TIMES, [300.0] + FREQS)
    assert espurio.n_onsets_take == len(TIMES) + 1, (
        f"{espurio.n_onsets_take} ataques de {len(TIMES) + 1} esperados"
    )
    assert espurio.rhythm >= 95.0, f"rhythm {espurio.rhythm:.1f} com um onset espurio antes"
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
    assert abs(track.onsets[0] - WINDOW_PAD_S) <= 0.03, (
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
    ataque. Sabotagem: WINDOW_PAD_S = 0 tem que ficar vermelho (medido em
    2026-09-12 no job real: pad 0 pega 4 de 5)."""
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
