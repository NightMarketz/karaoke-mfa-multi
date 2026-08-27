"""
tests/test_luminance_fence.py

Cerca de luminancia para o fundo atras da legenda de karaoke, e o piso de
intervalo entre flashes, conforme Recomendacao ITU-R BT.1702-3 (11/2023).

Category: Unit (no I/O, no subprocess)

Para que serve
--------------
A BT.1702-3 e o unico documento com numeros duros sobre quanto um fundo pode
variar. Ela mede risco de epilepsia fotossensivel, nao legibilidade -- nao
existe norma de broadcast limitando variacao de luminancia atras de legenda.
Reaproveitamos o limiar por ser o mais defensavel disponivel; quem citar o
numero deve cita-lo pelo que ele e.

Rodar
-----
    pytest tests/test_luminance_fence.py       # verifica contra a norma
    python tests/test_luminance_fence.py       # imprime as tabelas de consulta

ponytail: modulo mora em tests/ porque nada no pipeline o importa ainda.
Quando o render (scripts/08_render_video.py, 09_video_rendering.py) passar a
amostrar frames de verdade, promova luminance()/ceiling_code() para
karaoke/luminance.py e deixe so as asserts aqui.
"""
import pytest

# ── Constantes da norma ───────────────────────────────────────────────────────

SDR_PEAK_NITS = 200.0     # BT.1702-3 Nota 3: peak white SDR assumido
BT1886_GAMMA = 2.4        # EOTF de referencia, Rec. ITU-R BT.1886
FLASH_DELTA_NITS = 20.0   # Guideline 1: diferenca que caracteriza flash nocivo
MICHELSON_FLOOR_NITS = 160.0  # acima disso vale contraste Michelson 1/17 (so HDR)
FLASH_AREA_LIMIT = 0.25   # Guideline 1: >25% da tela, combinado com >3 flashes/s
FLASH_FLOOR_MS_50HZ = 360.0   # bordas de ataque separadas por >= isso: aceitavel
FLASH_FLOOR_MS_60HZ = 334.0

# Ancoras publicadas: Tabela 1 (SDR) e Notas 1-2 da BT.1702-3, em code 10-bit.
ITU_ANCHORS_10BIT = {
    64: 0.00, 160: 0.99, 400: 20.06, 520: 41.74,
    700: 92.75, 863: 160.40, 940: 200.00,
}


# ── Nucleo ────────────────────────────────────────────────────────────────────

def video_level(code: int, bits: int = 8) -> float:
    """Code value -> nivel de video normalizado V (preto 0, branco 1).

    BT.1702-3 nota de rodape da Tabela 1: V = (D-64)/876 para 10-bit.
    O equivalente 8-bit limited range e V = (D-16)/219, que e o que sai de um
    encode H.264 yuv420p.
    """
    if bits == 8:
        return (code - 16) / 219.0
    if bits == 10:
        return (code - 64) / 876.0
    raise ValueError(f"bits deve ser 8 ou 10, recebido {bits}")


def luminance(code: int, bits: int = 8, gamma: float = BT1886_GAMMA) -> float:
    """Luminancia de tela em cd/m2 para um code value SDR."""
    v = video_level(code, bits)
    return SDR_PEAK_NITS * (v ** gamma) if v > 0 else 0.0


def ceiling_code(code: int, bits: int = 8):
    """Code value mais claro permitido na mesma janela de 1 s.

    Retorna None quando a base ja esta em ou acima de 160 cd/m2, onde a norma
    troca para contraste Michelson 1/17 e aplica so a HDR.
    """
    base = luminance(code, bits)
    if base >= MICHELSON_FLOOR_NITS:
        return None
    top = 235 if bits == 8 else 940
    for candidate in range(code, top + 1):
        if luminance(candidate, bits) - base >= FLASH_DELTA_NITS:
            return candidate - 1
    return top


def flash_interval_ms(bpm: float, subdivision: int = 1) -> float:
    """Intervalo entre eventos, em ms. subdivision 1=seminima, 2=colcheia, 4=semicolcheia."""
    if bpm <= 0 or subdivision <= 0:
        raise ValueError("bpm e subdivision devem ser positivos")
    return 60_000.0 / (bpm * subdivision)


def flash_rate_ok(bpm: float, subdivision: int = 1, hz: int = 50) -> bool:
    """True se pulsar nessa subdivisao respeita o piso da BT.1702-3.

    Vale para efeito em QUADRO CHEIO. Abaixo de 25% da area de tela a
    proibicao de sequencia nao se aplica e este piso deixa de valer.
    """
    floor = FLASH_FLOOR_MS_50HZ if hz == 50 else FLASH_FLOOR_MS_60HZ
    return flash_interval_ms(bpm, subdivision) >= floor


def max_bpm(subdivision: int = 1, hz: int = 50) -> float:
    """Maior BPM que ainda respeita o piso, na subdivisao dada."""
    floor = FLASH_FLOOR_MS_50HZ if hz == 50 else FLASH_FLOOR_MS_60HZ
    return 60_000.0 / (floor * subdivision)


# ── Testes ────────────────────────────────────────────────────────────────────

class TestEotfAgainstStandard:
    """A EOTF tem que reproduzir os numeros publicados, nao so ser plausivel."""

    @pytest.mark.parametrize("code,expected", sorted(ITU_ANCHORS_10BIT.items()))
    def test_reproduces_itu_anchor(self, code, expected):
        assert luminance(code, bits=10) == pytest.approx(expected, abs=0.05)

    def test_all_seven_anchors_examined(self):
        # Cardinalidade antes do veredito: conjunto vazio seria verde universal.
        assert len(ITU_ANCHORS_10BIT) == 7

    def test_wrong_gamma_is_caught(self):
        """Controle negativo: sabotar a EOTF tem que deixar a checagem vermelha."""
        misses = [
            c for c, expected in ITU_ANCHORS_10BIT.items()
            if abs(luminance(c, bits=10, gamma=2.2) - expected) > 0.05
        ]
        assert len(misses) >= 5, "cerca nao detecta gamma errado, logo nao e cerca"

    def test_eight_and_ten_bit_agree_at_the_ends(self):
        # Re-derivacao por outro caminho: os dois ranges tem que fechar nos extremos.
        assert luminance(16, bits=8) == pytest.approx(luminance(64, bits=10), abs=0.01)
        assert luminance(235, bits=8) == pytest.approx(luminance(940, bits=10), abs=0.01)
        assert luminance(235, bits=8) == pytest.approx(SDR_PEAK_NITS, abs=0.01)


class TestCeiling:
    def test_monotonic_in_luminance(self):
        codes = range(16, 236)
        values = [luminance(c) for c in codes]
        assert all(a < b for a, b in zip(values, values[1:]))

    @pytest.mark.parametrize("base,expected", [
        (16, 99), (32, 100), (64, 108), (128, 148), (192, 203), (208, 218),
    ])
    def test_known_ceilings(self, base, expected):
        assert ceiling_code(base) == expected

    def test_ceiling_never_below_base(self):
        checked = [c for c in range(16, 236) if ceiling_code(c) is not None]
        assert len(checked) > 0, "nenhum code examinado: verde universal"
        assert all(ceiling_code(c) >= c for c in checked)

    def test_ceiling_delta_is_under_the_limit(self):
        """O teto tem que ficar ABAIXO de 20 cd/m2, e o proximo code, acima."""
        for c in range(16, 200, 8):
            top = ceiling_code(c)
            if top is None or top >= 235:
                continue
            assert luminance(top) - luminance(c) < FLASH_DELTA_NITS
            assert luminance(top + 1) - luminance(c) >= FLASH_DELTA_NITS

    def test_michelson_regime_returns_none(self):
        assert ceiling_code(224) is None
        assert luminance(224) >= MICHELSON_FLOOR_NITS

    def test_headroom_shrinks_as_background_brightens(self):
        """O achado que importa: fundo escuro e onde mora a liberdade."""
        assert ceiling_code(16) - 16 > ceiling_code(192) - 192


class TestFlashFloor:
    @pytest.mark.parametrize("bpm,subdivision,expected", [
        (120, 1, True),    # seminima a 120 -> 500 ms, passa
        (120, 2, False),   # colcheia a 120 -> 250 ms, viola
        (80, 2, True),     # colcheia a 80  -> 375 ms, passa
        (167, 1, False),   # seminima a 167 -> 359.3 ms, viola por pouco
    ])
    def test_rate_verdicts(self, bpm, subdivision, expected):
        assert flash_rate_ok(bpm, subdivision) is expected

    def test_max_bpm_agrees_with_interval(self):
        """Re-derivacao pelo outro lado: os dois sentidos tem que fechar."""
        for subdivision in (1, 2, 4):
            ceiling = max_bpm(subdivision)
            assert flash_rate_ok(ceiling - 0.1, subdivision) is True
            assert flash_rate_ok(ceiling + 0.1, subdivision) is False

    def test_published_ceilings(self):
        assert max_bpm(1) == pytest.approx(166.7, abs=0.1)
        assert max_bpm(2) == pytest.approx(83.3, abs=0.1)
        assert max_bpm(4) == pytest.approx(41.7, abs=0.1)

    def test_60hz_floor_is_more_permissive(self):
        assert max_bpm(1, hz=60) > max_bpm(1, hz=50)


# ── Tabelas de consulta ───────────────────────────────────────────────────────

def _print_tables():
    print("CERCA DE LUMINANCIA -- ITU-R BT.1702-3, SDR 8-bit limited range")
    print(f"L = {SDR_PEAK_NITS:.0f} * V^{BT1886_GAMMA}, V = (D-16)/219\n")
    print(f"{'base':>6} {'cd/m2':>9} {'teto':>6} {'cd/m2':>9} {'folga':>7}")
    rows = 0
    for code in range(16, 236, 16):
        base = luminance(code)
        top = ceiling_code(code)
        if top is None:
            print(f"{code:6d} {base:9.2f} {'--':>6} {'--':>9} {'--':>7}"
                  "  >=160 cd/m2: regime Michelson 1/17 (so HDR)")
        else:
            print(f"{code:6d} {base:9.2f} {top:6d} {luminance(top):9.2f} {top - code:+7d}")
        rows += 1
    print(f"\n{rows} linhas. Verificado contra {len(ITU_ANCHORS_10BIT)} ancoras publicadas.")

    print(f"\n\nPISO ENTRE FLASHES -- quadro cheio, {FLASH_FLOOR_MS_50HZ:.0f} ms (50 Hz)")
    print("Abaixo de 25% da area de tela este piso nao se aplica.\n")
    print(f"{'BPM':>5} {'1/4':>13} {'1/8':>13} {'1/16':>13}")
    for bpm in (80, 100, 120, 128, 140, 167, 174):
        cells = [
            f"{flash_interval_ms(bpm, sub):7.1f} ms "
            f"{'ok   ' if flash_rate_ok(bpm, sub) else 'VIOLA'}"
            for sub in (1, 2, 4)
        ]
        print(f"{bpm:5d} " + " ".join(cells))
    print(f"\nTeto: {max_bpm(1):.1f} BPM na seminima, {max_bpm(2):.1f} na colcheia, "
          f"{max_bpm(4):.1f} na semicolcheia.")


if __name__ == "__main__":
    _print_tables()
