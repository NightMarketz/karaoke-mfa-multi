"""Partes puras da bancada de loop: template e medidas. Sem ComfyUI."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("tlf", RAIZ / "scripts" / "teste_loop_fundo.py")
tlf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tlf)

VALORES_LOOP = {"seed": 1, "high_model": "a.safetensors", "high_lora": "b.safetensors",
                "high_lora_w": 0.0, "prompt": 'chuva "forte"', "image": "x.png",
                "width": 832, "height": 480, "length": 49}


def test_template_do_loop_preenche_e_amarra_inicio_ao_fim():
    g = tlf.preencher(tlf.WF_LOOP.read_text(encoding="utf-8"), VALORES_LOOP)
    flf = g["67"]["inputs"]
    assert flf["start_image"] == flf["end_image"] == ["62", 0]
    assert flf["length"] == 49 and g["6"]["inputs"]["text"] == 'chuva "forte"'


def test_template_da_imagem_preenche():
    g = tlf.preencher(tlf.WF_IMAGEM.read_text(encoding="utf-8"), {
        "seed": 7, "ckpt": "c.safetensors", "lora": "l.safetensors",
        "lora_w": 0.8, "prompt": "p"})
    assert g["10"]["inputs"]["strength_model"] == 0.8


def test_marcador_esquecido_levanta():
    faltando = dict(VALORES_LOOP)
    del faltando["length"]
    with pytest.raises(ValueError, match="length"):
        tlf.preencher(tlf.WF_LOOP.read_text(encoding="utf-8"), faltando)


def _quadros(n, fecha, respira=0.0):
    rng = np.random.default_rng(0)
    base = rng.uniform(0, 255, (8, 8, 3)).astype(np.float32)
    # ciclo: seno de periodo n (o quadro n seria o 0); sem ciclo: rampa que nao volta.
    # Fase pi/4 de proposito: com a emenda no ponto de maior velocidade a razao
    # de um ciclo PERFEITO e pi/2 = 1,57 e o limite de 1,5 reprova. Limite
    # herdado do make_loop_gif; no Wan FLF a emenda cai nos quadros amarrados,
    # onde o movimento desacelera. Se reprovar loop bom na pratica, e isto.
    passo = (np.sin(np.linspace(0, 2 * np.pi, n, endpoint=False) + np.pi / 4) if fecha
             else np.linspace(-1, 1, n))
    return np.stack([base + 10 * s + respira * s for s in passo])


def test_medir_aprova_ciclo_e_reprova_rampa():
    # controle negativo: rampa termina longe do comeco
    assert tlf.medir(_quadros(48, fecha=True))["fecha"] is True
    assert tlf.medir(_quadros(48, fecha=False))["fecha"] is False


def test_medir_ve_respiracao_da_faixa():
    calmo = tlf.medir(_quadros(48, True))["faixa_legenda_respiracao"]
    ofega = tlf.medir(_quadros(48, True, respira=40))["faixa_legenda_respiracao"]
    assert ofega > calmo * 3
