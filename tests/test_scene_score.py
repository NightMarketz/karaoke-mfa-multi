"""Partitura da cena reativa. Envelopes sinteticos, sem audio.

Os minimos esperados sao LITERAIS da spec, nao lidos do modulo: sabotar a
constante no modulo tem de deixar o teste vermelho.
"""
import numpy as np

from karaoke import scene_score as ss

FPS = 25


def _runs(est):
    """[(estado, n_quadros)] na ordem."""
    out = []
    for s in est:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([int(s), 1])
    return [tuple(r) for r in out]


def _serie(*trechos):
    """trechos: (valor_inicial, valor_final, segundos) -> e por quadro."""
    return np.concatenate([np.linspace(a, b, int(round(s * FPS)), endpoint=False)
                           for a, b, s in trechos])


def test_silencio_fica_todo_em_calmo():
    est, w, g = ss.score(np.zeros(3000), 0.01, [], FPS, 30.0)
    assert len(est) == 750, "cardinalidade: 30 s a 25 fps"
    assert (est == ss.CALMO).sum() == 750
    assert np.allclose(w[:, 0], 1.0)
    assert np.allclose(g, 1.0)


def test_volume_constante_nao_divide_por_zero():
    e = ss.envelope(np.full(3000, 0.3), 0.01, FPS, 30.0)
    assert len(e) == 750
    assert np.all(e == 0.0)


def test_subida_plato_queda_segue_a_ordem():
    e = _serie((0, 0, 5), (0, 1, 3), (1, 1, 8), (0, 0, 10))
    ordem = [s for s, _ in _runs(ss.estados(e, FPS))]
    assert ordem == [ss.CALMO, ss.TENSAO, ss.CLIMAX, ss.ESCURO, ss.CALMO]


def test_alto_constante_respeita_teto_e_cicla():
    est = ss.estados(np.ones(60 * FPS), FPS)
    runs = _runs(est)
    climax = [n for s, n in runs if s == ss.CLIMAX]
    assert len(climax) >= 1, "cardinalidade: tem de haver clímax"
    assert max(climax) <= 20 * FPS, f"clímax passou do teto: {max(climax)} quadros"
    ordem = [s for s, _ in runs]
    ciclo = [ss.CALMO, ss.TENSAO, ss.CLIMAX, ss.ESCURO, ss.CALMO]
    assert any(ordem[i:i + 5] == ciclo for i in range(len(ordem))), ordem


SEED = 2  # seeds 0..1 reprovadas na cardinalidade


def _passeio():
    rng = np.random.default_rng(SEED)
    return np.clip(0.5 + np.cumsum(rng.normal(0, 0.03, 300 * FPS)), 0, 1)


def test_nenhum_estado_abaixo_do_minimo():
    runs = _runs(ss.estados(_passeio(), FPS))
    completos = runs[1:-1]            # primeiro e ultimo podem estar cortados
    minimo = {ss.CALMO: 4.0, ss.TENSAO: 3.0, ss.CLIMAX: 3.0, ss.ESCURO: 2.5}
    vistos = {s: sum(1 for r, _ in completos if r == s) for s in minimo}
    assert all(n >= 2 for n in vistos.values()), f"cardinalidade: {vistos}"
    curtos = [(s, n) for s, n in completos if n < round(minimo[s] * FPS)]
    assert not curtos, f"{len(curtos)} de {len(completos)} runs abaixo do mínimo: {curtos[:5]}"


def test_pesos_somam_um_em_todo_quadro():
    e = _passeio()
    w = ss.pesos(ss.estados(e, FPS), e, FPS)
    assert w.shape == (len(e), 4) and len(e) > 0
    assert np.allclose(w.sum(axis=1), 1.0), f"{(~np.isclose(w.sum(1), 1)).sum()} de {len(e)} quadros"
    assert (w >= -1e-9).all()


def test_tensao_revela_mais_com_mais_energia():
    est = np.full(10 * FPS, ss.TENSAO)
    baixo = ss.pesos(est, np.full(10 * FPS, 0.0), FPS)[-1]
    alto = ss.pesos(est, np.full(10 * FPS, 1.0), FPS)[-1]
    assert np.allclose(baixo, [0.6, 0.4, 0, 0], atol=1e-6)
    assert np.allclose(alto, [0.0, 1.0, 0, 0], atol=1e-6)


def test_troca_nao_e_corte_seco():
    est = np.array([ss.CALMO] * FPS + [ss.CLIMAX] * (3 * FPS))
    w = ss.pesos(est, np.zeros(len(est)), FPS)
    assert 0.0 < w[FPS + 5, 2] < 1.0, "rampa de 1,2 s: no meio ainda mistura"
    assert np.isclose(w[FPS + int(1.2 * FPS) + 1, 2], 1.0)


def test_ganho_fogo_pulsa_e_decai():
    g = ss.ganho_fogo([1.0], FPS, 3 * FPS)
    assert np.isclose(g[FPS], 1.25)
    assert np.isclose(g[FPS - 1], 1.0)
    assert 1.0 < g[FPS + 8] < 1.125               # 0,32 s depois: 1 + 0,25·e^(-0,32/0,3) ≈ 1,086
    assert g[-1] < 1.01
