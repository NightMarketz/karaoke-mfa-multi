"""Unit tests para karaoke.background. HTTP dublado, sem rede."""
import json
from unittest.mock import patch

import pytest

from karaoke.background import IMAGE_RULES, build_brief, image_prompt


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _ollama_resposta(brief):
    return _FakeResp({"message": {"content": json.dumps({"brief": brief})}})


def test_brief_extrai_o_campo_do_json_estruturado():
    with patch("urllib.request.urlopen", return_value=_ollama_resposta("um mar escuro")):
        assert build_brief("qualquer letra") == "um mar escuro"


def test_brief_vazio_e_erro():
    with patch("urllib.request.urlopen", return_value=_ollama_resposta("   ")):
        with pytest.raises(ValueError, match="brief vazio"):
            build_brief("qualquer letra")


def test_prompt_de_imagem_carrega_as_regras_fixas():
    # As regras nao podem depender do LLM obedecer — vao literais no prompt.
    p = image_prompt("um mar escuro ao amanhecer")
    assert "um mar escuro ao amanhecer" in p
    assert IMAGE_RULES in p
    for exigido in ("no text", "no letters", "dark", "16:9"):
        assert exigido.lower() in p.lower(), f"regra ausente do prompt: {exigido}"


def test_letra_crua_nao_vaza_para_o_prompt_de_imagem():
    letra = "Andei por caminhos tortos, vi o sol nascer no mar"
    with patch("urllib.request.urlopen", return_value=_ollama_resposta("dark ocean dawn")):
        brief = build_brief(letra)
    p = image_prompt(brief)
    assert "caminhos tortos" not in p
