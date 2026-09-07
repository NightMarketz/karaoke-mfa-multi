"""Unit tests para karaoke.background. HTTP dublado, sem rede."""
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import stdout_protegido

from karaoke.background import (ANIMA_PREFIX, ANIMA_SUFFIX, COMFY_ENV_VAR,
                                COMFY_PORTS, _bust_cache, _diagnostico,
                                _inject_prompt, build_brief, generate_image,
                                image_prompt, resolve_comfy_host)
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


def _ollama_resposta(*tags):
    """Dubla a saida estruturada do Ollama: uma LISTA de tags, nao uma string.

    O esquema virou array com minItems porque o modelo devolvia uma tag so e
    a musica sumia do prompt. O duble segue o esquema real.
    """
    return _FakeResp({"message": {"content": json.dumps({"tags": list(tags)})}})


# 10 tags = MIN_TAGS, o piso que nao dispara retentativa.
_TAGS_OK = ("cityscape", "night", "rain", "neon lights", "wet asphalt",
            "reflection", "muted color", "wide shot", "horizon", "empty")


def test_brief_junta_as_tags_em_lista_separada_por_virgula():
    with patch("urllib.request.urlopen", return_value=_ollama_resposta(*_TAGS_OK)):
        assert build_brief("qualquer letra") == ", ".join(_TAGS_OK)


def test_brief_normaliza_caixa_e_underscore():
    # Regra do Anima: minuscula, espaco no lugar de underscore.
    sujas = ("Cityscape", "NIGHT_SKY", "neon_lights") + _TAGS_OK[3:]
    with patch("urllib.request.urlopen", return_value=_ollama_resposta(*sujas)):
        b = build_brief("qualquer letra")
    assert "_" not in b, b
    assert b == b.lower(), b
    assert "night sky" in b


def test_brief_vazio_e_erro():
    with patch("urllib.request.urlopen", return_value=_ollama_resposta("   ")):
        with pytest.raises(ValueError, match="brief vazio"):
            build_brief("qualquer letra")


def test_lista_curta_dispara_retentativa():
    # Uma tag so significa que a musica nao chegou ao prompt: o andaime fixo
    # geraria imagem bonita e generica, e nada denunciaria. Medido de verdade
    # com o llama3.2:3b, que devolveu "cityscape" sozinha.
    curta = _ollama_resposta("cityscape")
    boa = _ollama_resposta(*_TAGS_OK)
    with patch("urllib.request.urlopen", side_effect=[curta, boa]) as m:
        b = build_brief("qualquer letra")
    assert m.call_count == 2, "nao repetiu o pedido diante de lista curta"
    assert b == ", ".join(_TAGS_OK)


def test_prompt_de_imagem_monta_a_ordem_de_secao_do_anima():
    # O Anima le tags Danbooru em ordem de secao fixa: qualidade e safety
    # antes, conteudo no meio, composicao depois. O andaime nao pode depender
    # do LLM obedecer — vai literal.
    p = image_prompt("cityscape, night, rain, neon lights")
    assert p.startswith(ANIMA_PREFIX), p
    assert p.endswith(ANIMA_SUFFIX), p
    assert "cityscape, night, rain, neon lights" in p

    # "no humans" e "scenery" sao o conserto estrutural do rosto no centro:
    # tag que o modelo aprendeu, em vez de pedido em prosa.
    for exigido in ("no humans", "scenery", "empty foreground"):
        assert exigido in p, f"tag ausente do andaime: {exigido}"

    # Peso no Anima precisa de multiplicador forte (guia: (tag:2), nao (tag:1.1)).
    assert "(dark:2)" in p, p

    # O Anima-Aesthetic recomenda NAO usar score tags no positivo.
    assert "score_" not in p, f"score tag vazou para o positivo: {p}"


def test_conteudo_do_brief_fica_entre_o_prefixo_e_o_sufixo():
    # Ordem importa para este modelo: conteudo depois de qualidade/safety e
    # antes da composicao. Se o brief for parar fora dessa janela, a ordem
    # de secao quebra sem nenhum erro visivel.
    p = image_prompt("ocean, dusk")
    meio = p[len(ANIMA_PREFIX):len(p) - len(ANIMA_SUFFIX)]
    assert meio == "ocean, dusk", f"conteudo fora da janela: {meio!r}"


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
               return_value=_ollama_resposta(*_TAGS_OK)):
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
    # O 08b sequestra sys.stdout na importacao, como 18 dos 26 scripts. Sem a
    # guarda o wrapper fecha o temporario da captura do pytest ao ser coletado
    # e envenena o resto da suite. Ver conftest.stdout_protegido.
    with stdout_protegido():
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


# --------------------------------------------------------------------------
# H3: a porta do ComfyUI nao e fixa (8000/8001/8188 ja vistas nesta maquina).
# Todo teste aqui dubla o urlopen — nenhum toca a rede.
# --------------------------------------------------------------------------

def _sonda(portas_vivas):
    """urlopen que so responde nas portas listadas. Registra quem foi tentado."""
    tentadas = []

    def _fake(url, timeout=None):
        tentadas.append(url)
        porta = int(url.split(":")[2].split("/")[0])
        if porta not in portas_vivas:
            raise OSError(f"conexao recusada em {porta}")
        return _FakeResp({"system": {}})

    return _fake, tentadas


def test_env_var_vence_e_nao_sonda(monkeypatch):
    monkeypatch.setenv(COMFY_ENV_VAR, "http://10.0.0.5:9999/")
    _fake, tentadas = _sonda(set(COMFY_PORTS))
    with patch("urllib.request.urlopen", side_effect=_fake):
        assert resolve_comfy_host() == "http://10.0.0.5:9999"
    assert tentadas == [], f"sondou {len(tentadas)} porta(s) com {COMFY_ENV_VAR} setada"


@pytest.mark.parametrize("vivas,esperada", [
    ({8188, 8000, 8001}, 8188),   # todas de pe -> a primeira da ordem
    ({8000, 8001}, 8000),         # 8188 morta -> cai para a proxima
    ({8001}, 8001),               # so a ultima
])
def test_sondagem_pega_o_primeiro_que_responde(monkeypatch, vivas, esperada):
    monkeypatch.delenv(COMFY_ENV_VAR, raising=False)
    _fake, tentadas = _sonda(vivas)
    with patch("urllib.request.urlopen", side_effect=_fake):
        assert resolve_comfy_host() == f"http://127.0.0.1:{esperada}"
    ordem = [int(u.split(":")[2].split("/")[0]) for u in tentadas]
    assert ordem == list(COMFY_PORTS[:COMFY_PORTS.index(esperada) + 1]), (
        f"sondou {ordem}, esperado parar em {esperada}"
    )


def test_nenhuma_porta_responde_nomeia_todas_as_candidatas(monkeypatch):
    """O aviso do 08b tem de dizer ONDE procurou. Um ConnectionRefused pelado
    aponta so a primeira porta e manda o usuario para o lugar errado."""
    monkeypatch.delenv(COMFY_ENV_VAR, raising=False)
    _fake, tentadas = _sonda(set())
    with patch("urllib.request.urlopen", side_effect=_fake):
        with pytest.raises(RuntimeError) as exc:
            resolve_comfy_host()
    texto = str(exc.value)
    faltando = [p for p in COMFY_PORTS if str(p) not in texto]
    assert not faltando, (
        f"{len(faltando)} de {len(COMFY_PORTS)} candidatas ausentes da mensagem: "
        f"{faltando} — mensagem: {texto!r}"
    )
    assert COMFY_ENV_VAR in texto, f"a saida de escape nao e citada: {texto!r}"
    assert len(tentadas) == len(COMFY_PORTS), (
        f"{len(tentadas)} de {len(COMFY_PORTS)} candidatas sondadas"
    )


def test_host_explicito_pula_a_resolucao_inteira(monkeypatch):
    """As chamadas com host= nao podem sondar nada — e o que mantem os testes
    (e um caller que sabe o endereco) fora da rede."""
    monkeypatch.setenv(COMFY_ENV_VAR, "http://nao-deve-ser-usado:1")
    urls = []

    def _captura(url, payload, timeout):
        urls.append(url)
        raise RuntimeError("parada proposital")

    with patch("karaoke.background._post_json", side_effect=_captura):
        with pytest.raises(RuntimeError, match="parada proposital"):
            generate_image("um mar escuro", Path("x.png"),
                           _escreve_template(), host=HOST_FAKE)
    assert urls == [f"{HOST_FAKE}/prompt"], urls
