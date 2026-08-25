"""Unit tests para karaoke.background. HTTP dublado, sem rede."""
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from karaoke.background import (IMAGE_RULES, _bust_cache, _diagnostico,
                                _inject_prompt, build_brief, generate_image,
                                image_prompt)
import karaoke.paths as kpaths

# Host explicito em todo teste: `generate_image(host=...)` pula a resolucao,
# entao nenhum teste sonda porta nenhuma. Rede zero.
HOST_FAKE = "http://127.0.0.1:65535"

# Template como o README manda escrever: marcadores no lugar dos valores. O
# `%seed%` sai sem aspas de proposito — o arquivo so vira JSON valido depois
# da substituicao, que e justamente o que _inject_prompt tem de garantir.
TEMPLATE_MARCADO = """{
  "3": {"class_type": "KSampler", "inputs": {"seed": %seed%, "steps": 8}},
  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "%prompt%"}},
  "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "karaoke/bg"}}
}"""


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


def test_letra_crua_nao_vaza_para_o_no_do_comfyui(tmp_path):
    """A fronteira real: o texto que generate_image injeta no no do workflow.

    A versao anterior deste teste passava o brief como constante fixa e
    afirmava que a letra nao estava nela — verdadeiro por construcao,
    independente do codigo. Aqui o brief atravessa build_brief, image_prompt e
    _inject_prompt, e a assercao e sobre o que de fato sai no payload do
    ComfyUI.
    """
    letra = "Andei por caminhos tortos, vi o sol nascer no mar de Ipanema"
    with patch("urllib.request.urlopen",
               return_value=_ollama_resposta("A dark ocean at dawn, muted teal")):
        brief = build_brief(letra)

    wf_path = tmp_path / "wf.json"
    wf_path.write_text(TEMPLATE_MARCADO, encoding="utf-8")

    capturado = {}

    def _captura(url, payload, timeout):
        capturado["prompt"] = payload["prompt"]
        raise RuntimeError("parada proposital antes do poll")

    with patch("karaoke.background._post_json", side_effect=_captura):
        with pytest.raises(RuntimeError, match="parada proposital"):
            generate_image(image_prompt(brief), tmp_path / "bg.png", wf_path,
                           host=HOST_FAKE)

    injetado = capturado["prompt"]["6"]["inputs"]["text"]
    assert "%prompt%" not in injetado, "o marcador sobreviveu — nada foi injetado"
    # Fiacao do H1: o nonce tem de estar no payload que SAI, nao so na funcao.
    prefixo = capturado["prompt"]["9"]["inputs"]["filename_prefix"]
    assert prefixo != "karaoke/bg" and prefixo.startswith("karaoke/bg_"), (
        f"generate_image submeteu o prefixo cru (cache do ComfyUI): {prefixo!r}"
    )

    palavras = [w for w in re.findall(r"\w+", letra.lower()) if len(w) >= 4]
    assert len(palavras) >= 5, f"so {len(palavras)} palavras testaveis na letra"
    vazadas = [w for w in palavras if w in injetado.lower()]
    assert not vazadas, (
        f"{len(vazadas)} de {len(palavras)} palavras da letra crua chegaram ao "
        f"gerador de imagem: {vazadas} — texto injetado: {injetado!r}"
    )


def test_prompt_hostil_sobrevive_intacto_ao_json():
    """H4: o brief entra ESCAPADO dentro das aspas do template.

    Aspas e barras invertidas no brief (o LLM escreve texto livre) sao o que
    quebraria o JSON se o marcador fosse trocado cru. A assercao e sobre a
    ESTRUTURA parseada, nao sobre substring do texto.
    """
    hostil = 'a \\ backslash and a "quote" and a %seed% look-alike'
    grafo = _inject_prompt(TEMPLATE_MARCADO, hostil)   # nao levanta -> JSON valido
    assert grafo["6"]["inputs"]["text"] == hostil, (
        f"prompt corrompido na ida e volta: {grafo['6']['inputs']['text']!r}"
    )


def test_seed_vira_inteiro_cru_e_o_grafo_parseia():
    """%seed% e numero sem aspas no template: `"seed": %seed%` so vira JSON
    valido DEPOIS da troca. Se sair como string, o ComfyUI rejeita o no."""
    seeds = set()
    for _ in range(5):
        grafo = _inject_prompt(TEMPLATE_MARCADO, "um mar escuro")
        seed = grafo["3"]["inputs"]["seed"]
        assert isinstance(seed, int) and not isinstance(seed, bool), (
            f"seed saiu como {type(seed).__name__}: {seed!r}"
        )
        assert 0 <= seed < 2 ** 32, f"seed fora da faixa: {seed}"
        seeds.add(seed)
    assert len(seeds) > 1, f"5 chamadas produziram {len(seeds)} seed(s) distintas"


def test_template_sem_marcador_de_prompt_e_erro():
    """Um export cru da GUI nao tem marcador. Renderizar o placeholder em
    silencio seria pior que falhar: o job sai com a imagem errada e nada avisa.
    """
    cru = json.dumps({"6": {"class_type": "CLIPTextEncode",
                            "inputs": {"text": "beautiful scenery"}}})
    with pytest.raises(ValueError, match="%prompt%"):
        _inject_prompt(cru, "um mar escuro")


def _escreve_template():
    """Template marcado num arquivo temporario (generate_image le do disco)."""
    import tempfile
    f = Path(tempfile.mkdtemp()) / "wf.json"
    f.write_text(TEMPLATE_MARCADO, encoding="utf-8")
    return f


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


# --------------------------------------------------------------------------
# H1: cache do ComfyUI. Grafo identico -> execution_cached, outputs vazio.
# --------------------------------------------------------------------------

def _prefixos(grafo):
    return [n["inputs"]["filename_prefix"]
            for n in grafo.values() if "filename_prefix" in n.get("inputs", {})]


def test_duas_submissoes_identicas_geram_prefixos_diferentes():
    """Sem nonce, o segundo render da MESMA musica volta cacheado e sem imagem
    — o 08b avisa e cai no fundo chapado, em silencio, para sempre."""
    a = _inject_prompt(TEMPLATE_MARCADO, "um mar escuro")
    b = _inject_prompt(TEMPLATE_MARCADO, "um mar escuro")
    assert _bust_cache(a) == 1 and _bust_cache(b) == 1
    pa, pb = _prefixos(a), _prefixos(b)
    assert len(pa) == len(pb) == 1, f"{len(pa)} e {len(pb)} prefixos — teste inutil"
    assert pa[0] != pb[0], f"prefixo repetido nas duas submissoes: {pa[0]!r}"
    assert pa[0].startswith("karaoke/bg_"), f"prefixo original perdido: {pa[0]!r}"


def test_todos_os_nos_que_salvam_arquivo_recebem_o_nonce():
    """Varredura completa: supor um unico SaveImage deixaria os outros
    cacheados. A contagem examinada e a alterada tem de fechar."""
    grafo = {
        "1": {"class_type": "KSampler", "inputs": {"seed": 7}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "a"}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "b/c"}},
        "11": {"class_type": "SaveAnimatedWEBP", "inputs": {"filename_prefix": "d"}},
        "12": {"class_type": "PreviewImage", "inputs": {}},
    }
    examinados = len(grafo)
    com_prefixo = len(_prefixos(grafo))
    assert examinados == 5 and com_prefixo == 3, (
        f"fixture drift: {examinados} nos, {com_prefixo} com filename_prefix"
    )
    mudados = _bust_cache(grafo)
    assert mudados == com_prefixo, (
        f"{mudados} de {com_prefixo} nos com filename_prefix (em {examinados} "
        f"nos no total) receberam nonce"
    )
    novos = _prefixos(grafo)
    assert len(novos) == com_prefixo
    sufixos = {p.rsplit("_", 1)[1] for p in novos}
    assert len(sufixos) == 1, f"nonce diferente por no: {sufixos}"
    assert [p.rsplit("_", 1)[0] for p in novos] == ["a", "b/c", "d"], novos


def test_grafo_sem_filename_prefix_nao_conta_como_cache_quebrado():
    """Caso explicito: zero campos == zero alteracoes, NAO 'tudo pronto'.

    Um grafo assim nao salva arquivo nenhum, entao nao ha cache a sujar — e o
    sintoma vira outputs vazio, capturado pelo _diagnostico (H2). O retorno 0
    existe para que isso nunca passe por sucesso."""
    grafo = {"1": {"class_type": "KSampler", "inputs": {"seed": 7}},
             "2": {"class_type": "PreviewImage", "inputs": {}}}
    assert _bust_cache(grafo) == 0, "contou alteracao onde nao ha filename_prefix"


# --------------------------------------------------------------------------
# H2: status=success com outputs vazio. Ler o log, nao o status.
# --------------------------------------------------------------------------

def _history_vazio(entry):
    """urlopen dublado: /prompt via _post_json, /history via urlopen."""
    return _FakeResp({"pid": entry})


def test_outputs_vazio_leva_a_reclamacao_do_comfyui_para_a_excecao():
    entry = {
        "outputs": {},
        "status": {
            "status_str": "success",
            "messages": [["execution_error",
                          {"exception_message": "CheckpointLoaderSimple: modelo z_image ausente"}]],
        },
    }
    with patch("karaoke.background._post_json", return_value={"prompt_id": "pid"}):
        with patch("urllib.request.urlopen", return_value=_history_vazio(entry)):
            with pytest.raises(RuntimeError) as exc:
                generate_image("um mar escuro", Path("nao_usado.png"),
                               _escreve_template(), host=HOST_FAKE)
    texto = str(exc.value)
    for esperado in ("sem produzir imagem", "success", "z_image ausente"):
        assert esperado in texto, f"{esperado!r} ausente da excecao: {texto!r}"


@pytest.mark.parametrize("entry,esperado", [
    ({"outputs": {}}, "sem diagnostico"),                       # sem status
    ({"outputs": {}, "status": None}, "sem diagnostico"),       # status nulo
    ({"outputs": {}, "status": {"status_str": "error"}}, "error"),   # sem messages
    ({"outputs": {}, "status": {"messages": []}}, "sem diagnostico"),
    ({"status": {"messages": [["x", {"y": 1}]]}}, "'y': 1"),    # sem outputs
])
def test_diagnostico_degrada_em_vez_de_estourar(entry, esperado):
    """Mudanca de esquema tem de virar mensagem pobre, nunca KeyError dentro
    do proprio caminho de erro."""
    assert esperado in _diagnostico(entry)


def test_diagnostico_e_truncado():
    entry = {"status": {"status_str": "e", "messages": ["x" * 5000]}}
    assert len(_diagnostico(entry)) <= 600
