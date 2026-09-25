"""Partes puras da bancada de loop: template e medidas. Sem ComfyUI."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("tlf", RAIZ / "scripts" / "teste_loop_fundo.py")
tlf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tlf)

VALORES_LOOP = {"seed": 1, "prompt": 'chuva "forte"', "image": "x.png",
                "width": 1024, "height": 576, "length": 124}


def test_template_do_loop_preenche_e_amarra_inicio_ao_fim():
    g = tlf.preencher(tlf.WF_LOOP.read_text(encoding="utf-8"), VALORES_LOOP)
    guias = [n["inputs"] for n in g.values() if n["class_type"] == "MiniMaxH3AddGuide"]
    assert {gi["frame_idx"] for gi in guias} >= {0, -1}
    assert all(gi["image"] == ["114", 0] for gi in guias) and g["114"]["inputs"]["image"] == "x.png"
    ref = g["104"]["inputs"]
    assert ref["length"] == 124 and ref["prompt"] == 'chuva "forte"'


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


def test_template_one_obsession_preenche_so_com_prompt_e_seed():
    g = tlf.preencher((RAIZ / "config" / "comfy_workflow_one_obsession.json")
                      .read_text(encoding="utf-8"), {"seed": 3, "prompt": "scenery"})
    assert g["1"]["inputs"]["unet_name"] == "oneObsession_anima29BV1.safetensors"
    assert g["2"]["inputs"]["clip_name"] == "qwen_3_06b_base.safetensors"  # identico byte a byte ao _txt do Civitai (SHA256 CD2A5120...)


def test_template_h3_loop_ref2va_ancora_a_base_em_cinco_quadros():
    g = tlf.preencher(tlf.WF_LOOP.read_text(encoding="utf-8"), VALORES_LOOP)
    assert g["6"]["inputs"]["unet_name"] == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    guias = sorted(n["inputs"]["frame_idx"] for n in g.values() if n["class_type"] == "MiniMaxH3AddGuide")
    assert guias == [-1, 0, 31, 62, 93]


def test_quadros_fora_da_grade_do_h3_levanta():
    # 22 esta na grade, mas a ancora 31 nao cabe (erro real do ComfyUI)
    assert tlf.grade_h3(107) and tlf.grade_h3(124)
    assert not tlf.grade_h3(49) and not tlf.grade_h3(22)
