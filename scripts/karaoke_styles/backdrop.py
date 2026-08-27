"""
backdrop.py — Paleta e emissão de comandos do fundo procedural (fatia A).

A paleta é indexada pelos valores de `color` de STYLE_DEFAULTS (5), não pelos
style keys (9). Um rótulo de seção novo herda um fundo de graça, e isto não
vira mais uma superfície seção→X (ver docs/tasks/section-style-map-duplication.md).

Os valores são deltas aplicados pelo filtro `huesaturation` do ffmpeg sobre um
gradiente de cores fixas — `gradients` não aceita comando em c0-c7.
"""

from __future__ import annotations

NEUTRAL: dict[str, float] = {"hue": 0.0, "saturation": 0.0, "intensity": 0.0}

BACKDROP_PALETTE: dict[str, dict[str, float]] = {
    "soft":    {"hue": -20.0, "saturation": -0.35, "intensity": -0.10},
    "default": {"hue":   0.0, "saturation":  0.00, "intensity":  0.00},
    "cool":    {"hue":  40.0, "saturation":  0.10, "intensity": -0.05},
    "warm":    {"hue": -55.0, "saturation":  0.20, "intensity":  0.05},
    "intense": {"hue": -75.0, "saturation":  0.45, "intensity":  0.15},
}


def backdrop_for_color(color: str) -> dict[str, float]:
    """Deltas de huesaturation para um token de cor. Desconhecido -> neutro."""
    return dict(BACKDROP_PALETTE.get(color, NEUTRAL))


_FILTER = "huesaturation"
_ALLOWED: dict[str, tuple[float, float]] = {
    "hue": (-180.0, 180.0),
    "saturation": (-1.0, 1.0),
    "intensity": (-1.0, 1.0),
}


def _command(t: float, param: str, value: float, last_t: float) -> str:
    """Uma linha de sendcmd, validada. Fronteira de confianca da fatia A."""
    if param not in _ALLOWED:
        raise ValueError(f"parametro fora da whitelist: {param!r}")
    low, high = _ALLOWED[param]
    if not isinstance(value, (int, float)) or not (low <= float(value) <= high):
        raise ValueError(f"{param}={value!r} fora da faixa [{low}, {high}]")
    if t < 0.0 or t < last_t:
        raise ValueError(f"timestamp nao-monotonico: {t} apos {last_t}")
    return f"{t:.3f} {_FILTER} {param} {float(value):.4f};"


def emit_backdrop_commands(lines: list[dict]) -> str:
    """analysis["lines"] -> conteudo de backdrop.cmd. Um bloco por troca de cor."""
    out: list[str] = []
    previous_colour: object = object()
    last_t = 0.0
    for index, line in enumerate(lines):
        colour = line.get("color")
        if colour == previous_colour:
            continue
        # O primeiro bloco ancora em 0 para o fundo ja nascer certo.
        t = 0.0 if index == 0 else float(line.get("start", 0.0))
        for param, value in backdrop_for_color(colour).items():
            out.append(_command(t, param, value, last_t))
        last_t = t
        previous_colour = colour
    return "\n".join(out)
