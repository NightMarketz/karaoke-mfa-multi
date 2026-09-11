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


def test_take_sem_ataque_suficiente_nao_inventa_nota(ref):
    """Controle negativo: take mudo tem que dar nota baixa com denominador visivel."""
    r = score(ref, track_from_audio(np.zeros(int(2.0 * SR), dtype=np.float32), SR))
    assert r.n_onsets_take == 0, f"silencio gerou {r.n_onsets_take} ataques"
    assert r.n_frames_compared == 0, "sem contorno nao ha frames comparados"
    assert r.rhythm == 0.0 and r.melody == 0.0
    assert r.total < 25.0, f"take mudo recebeu {r.total:.1f}"


from karaoke.scorer import track_from_word_timing


def test_karaoke_usa_inicios_de_palavra_como_ataques():
    """Os ataques vem do gabarito, o contorno vem do audio."""
    words = [
        {"word": "um", "start": 0.30, "end": 0.55, "score": 1.0},
        {"word": "dois", "start": 0.90, "end": 1.15, "score": 1.0},
        {"word": "tres", "start": 1.50, "end": 1.75, "score": 1.0},
        {"word": "quatro", "start": 2.40, "end": 2.65, "score": 1.0},
        {"word": "cinco", "start": 3.00, "end": 3.25, "score": 1.0},
    ]
    audio = bursts(TIMES, FREQS)
    track = track_from_word_timing(words, audio, SR)

    assert len(track.onsets) == len(words), (
        f"{len(track.onsets)} ataques de {len(words)} palavras"
    )
    assert track.onsets[0] == pytest.approx(0.30)
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
    assert r.total >= 80.0, f"karaoke contra si mesmo deu {r.total:.1f}"
