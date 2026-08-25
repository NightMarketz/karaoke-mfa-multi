"""Unit tests para karaoke.background. HTTP dublado, sem rede."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from karaoke.background import IMAGE_RULES, build_brief, image_prompt
import karaoke.paths as kpaths


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


def test_prompt_e_injetado_no_no_positivo():
    from karaoke.background import _inject_prompt
    wf = {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "PLACEHOLDER"}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "kstudio"}},
    }
    out = _inject_prompt(wf, "um mar escuro", node_id="6")
    assert out["6"]["inputs"]["text"] == "um mar escuro"
    assert wf["6"]["inputs"]["text"] == "PLACEHOLDER", "mutou o workflow original"


def test_no_positivo_inexistente_e_erro():
    from karaoke.background import _inject_prompt
    with pytest.raises(KeyError, match="99"):
        _inject_prompt({"6": {"class_type": "CLIPTextEncode", "inputs": {}}},
                       "x", node_id="99")


def _load_cli_module():
    """Importa scripts/08b_background_image.py como modulo (nome numerico)."""
    spec_path = Path(__file__).parent.parent / "scripts" / "08b_background_image.py"
    spec = importlib.util.spec_from_file_location("background_image_cli", str(spec_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["background_image_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_falha_na_geracao_nao_derruba_o_job():
    """A constraint que mais importa: geracao falha -> processo segue (exit 0),
    nao levanta excecao, nao chama sys.exit com codigo != 0."""
    job_id = "test_08b_exit0"
    job_dir = kpaths.job_root(job_id)
    shutil.rmtree(job_dir, ignore_errors=True)
    kpaths.lyrics_path(job_id).parent.mkdir(parents=True, exist_ok=True)
    kpaths.lyrics_path(job_id).write_text("qualquer letra", encoding="utf-8")
    assert not kpaths.background_png(job_id).exists()

    # O script reatribui sys.stdout/stderr a nivel de modulo (io.TextIOWrapper
    # em volta do .buffer compartilhado com o pytest). Precisa restaurar E
    # destacar (detach) o wrapper antes de descarta-lo — senao o GC fecha o
    # buffer compartilhado quando o wrapper e coletado, e quebra a captura
    # do pytest para os testes seguintes ("I/O operation on closed file").
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    wrapped_stdout, wrapped_stderr = orig_stdout, orig_stderr
    try:
        mod = _load_cli_module()
        wrapped_stdout, wrapped_stderr = sys.stdout, sys.stderr
        with patch.object(mod, "build_brief", side_effect=RuntimeError("ollama fora do ar")):
            with patch("sys.argv", ["08b_background_image.py", "--job-id", job_id]):
                mod.main()  # nao deve levantar
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr
        if wrapped_stdout is not orig_stdout:
            wrapped_stdout.detach()
        if wrapped_stderr is not orig_stderr:
            wrapped_stderr.detach()
        shutil.rmtree(job_dir, ignore_errors=True)
