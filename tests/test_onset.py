import numpy as np
import pytest

from karaoke.audio_fixtures import SR, bursts as _bursts
from karaoke.onset import compute_rms, detect_onsets


def test_detecta_todos_os_ataques_conhecidos():
    times = [0.3, 0.9, 1.5, 2.4, 3.0]
    audio = _bursts(times, [220, 247, 262, 294, 330])

    rms, frame_dur = compute_rms(audio, SR)
    onsets = detect_onsets(rms, frame_dur)

    # denominador junto do numero
    assert len(onsets) == len(times), (
        f"detectou {len(onsets)} de {len(times)} ataques esperados: {onsets}"
    )
    erro_max = max(min(abs(o - t) for t in times) for o in onsets)
    assert erro_max <= 0.035, f"erro maximo {erro_max:.3f}s acima de 0.035s"


def test_silencio_nao_produz_ataque():
    """Controle negativo: sem energia nao ha ataque, e zero aqui e o resultado CORRETO."""
    audio = np.zeros(int(2.0 * SR), dtype=np.float32)
    rms, frame_dur = compute_rms(audio, SR)
    onsets = detect_onsets(rms, frame_dur)
    assert len(onsets) == 0, f"silencio gerou {len(onsets)} ataques"


def test_gap_minimo_funde_ataques_colados():
    """Dois bursts a 0.04s (abaixo de MIN_GAP_S=0.08) contam como um."""
    audio = _bursts([0.5, 0.54], [300, 300], dur=0.1)
    rms, frame_dur = compute_rms(audio, SR)
    onsets = detect_onsets(rms, frame_dur)
    assert len(onsets) == 1, f"esperava 1 ataque fundido, veio {len(onsets)}: {onsets}"


def test_cardinalidade_do_rms():
    """Um audio de 1s a hop de 10ms tem ~100 frames; zero seria falha silenciosa."""
    audio = _bursts([0.1], [300], dur=0.5)
    rms, frame_dur = compute_rms(audio, SR)
    assert len(rms) > 50, f"apenas {len(rms)} frames de RMS — populacao vazia nao valida nada"
    assert frame_dur == pytest.approx(0.010, abs=1e-6)
