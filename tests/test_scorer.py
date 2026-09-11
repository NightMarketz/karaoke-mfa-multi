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
