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
