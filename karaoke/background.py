"""
Gera a ilustracao de fundo a partir da letra, tudo local.

Brief:  Ollama  (llama3.2:3b, saida estruturada)
Imagem: ComfyUI (z_image_turbo, HTTP)

Nada aqui pode derrubar o job: quem chama trata excecao e cai no fundo chapado.
"""
import json
import os
import random
import shutil
import time
import uuid
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://127.0.0.1:11434"
BRIEF_MODEL = "llama3.2:3b"            # qwen3:4b devolve as proprias instrucoes

# A porta do ComfyUI nao e fixa: o app ja subiu em 8000, 8001 e 8188 em
# sessoes diferentes desta maquina. COMFYUI_URL (mesmo nome usado no outro
# projeto) vence e vai literal; sem ela, sonda nesta ordem.
COMFY_ENV_VAR = "COMFYUI_URL"
COMFY_PORTS = (8188, 8000, 8001)
COMFY_PROBE_SECONDS = 1.5

COMFY_OUTPUT_ROOT = Path("C:/ComfyUI")
COMFY_POLL_SECONDS = 2
COMFY_TIMEOUT_SECONDS = 300

_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "brief": {
            "type": "string",
            "description": (
                "The visual brief, written in ENGLISH. Never in the language of "
                "the lyrics."
            ),
        }
    },
    "required": ["brief"],
}

# Medido com a letra da "Publi" (portugues): o modelo respondia em portugues e
# descrevia cenas de centro claro ("cidade iluminada por luz branca"), apesar
# das regras. Duas licoes viraram texto aqui:
#   1. a exigencia de idioma vem PRIMEIRO e sozinha — no fim da lista ela perde;
#   2. restricao de composicao tem de estar no BRIEF, nao so no sufixo colado
#      depois: o conteudo do brief vence o sufixo na atencao do modelo.
_BRIEF_SYSTEM = (
    "WRITE IN ENGLISH ONLY. The lyrics may be in any language; your answer is "
    "always English. Never answer in the language of the lyrics.\n\n"
    "You write visual briefs for karaoke video background illustrations. Read "
    "the lyrics for their mood and imagery, then write ONE English paragraph "
    "(max 55 words) describing a background illustration.\n\n"
    "The image is a BACKDROP behind song lyrics, not a poster:\n"
    "- The lower third stays dark and empty — the lyrics are drawn over it.\n"
    "- Nothing in the centre: no face, no figure, no focal object there.\n"
    "- Favour wide scenery, atmosphere, texture and light over characters.\n"
    "- Overall dark and low-contrast, so white text stays readable on top.\n"
    "- No text, letters, words, numbers, logos or screens showing writing.\n"
    "Describe only what should be visible. Never name something to exclude — "
    "naming it makes the image model draw it."
)

# Sinais baratos de que a resposta nao saiu em ingles. Nao e deteccao de idioma
# de verdade: e uma cerca contra o caso medido (portugues/espanhol vazando),
# e falso negativo aqui so custa uma imagem pior, nunca uma falha do job.
_NAO_INGLES = ("ã", "õ", "ç", "á", "é", "í", "ó", "ú", "â", "ê", "ô", "ñ")


def _parece_ingles(texto: str) -> bool:
    return not any(c in texto.lower() for c in _NAO_INGLES)


# Medido: o brief pediu "a giant screen displays a news headline" e o Z-Image
# desenhou letras tortas no telhado e no telao. A regra "no text" no sufixo nao
# salva quando o proprio brief PEDE escrita — o conteudo vence o sufixo. Entao
# a cerca e no brief, antes da imagem existir.
_PEDE_ESCRITA = (
    "headline", "sign", "signage", "billboard", "banner", "poster",
    "screen", "text", "letter", "word", "logo", "writing", "caption",
    "label", "slogan", "marquee", "graffiti", "newspaper",
)


def _pede_escrita(texto: str) -> list:
    """Termos no brief que puxam texto para dentro da imagem."""
    baixo = texto.lower()
    return [t for t in _PEDE_ESCRITA if t in baixo]

# O workflow usa ConditioningZeroOut como negativo, entao TUDO vai no prompt
# positivo. Por isso a composicao e descrita pelo que DEVE estar la ("empty
# dark foreground") em vez do que nao deve: nomear o indesejado no positivo
# tende a desenha-lo. As unicas negacoes que ficam sao as de texto, que foram
# medidas funcionando (2 de 2 geracoes sem uma letra sequer).
IMAGE_RULES = (
    "illustration, painterly, wide atmospheric background, "
    "empty dark foreground, deep shadows across the lower third, "
    "low contrast, muted palette, negative space in the centre, "
    "no text, no letters, no words, no watermark, 16:9"
)


def _post_json(url: str, payload: dict, timeout: int):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _pedir_brief(lyrics: str, model: str, host: str, reforco: str = "") -> str:
    body = _post_json(
        f"{host}/api/chat",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _BRIEF_SYSTEM + reforco},
                {"role": "user", "content": f"LYRICS:\n{lyrics}"},
            ],
            "stream": False,
            "think": False,
            "format": _BRIEF_SCHEMA,
            "options": {"temperature": 0.8},
        },
        timeout=300,
    )
    return json.loads(body["message"]["content"])["brief"].strip()


def build_brief(lyrics: str, model: str = BRIEF_MODEL, host: str = OLLAMA_HOST) -> str:
    """Letra -> um paragrafo de direcao visual, em ingles. Levanta se falhar.

    O modelo pequeno responde no idioma da letra apesar da instrucao (medido
    com a "Publi"). Pedir de novo custa ~5s e o Z-Image e treinado em ingles,
    entao a segunda tentativa se paga. Se ainda assim vier em outro idioma,
    seguimos com o que veio: brief torto gera imagem pior, brief nenhum nao
    gera imagem alguma.
    """
    brief = _pedir_brief(lyrics, model, host)

    problemas = []
    if brief and not _parece_ingles(brief):
        problemas.append("Your previous answer was NOT in English. "
                         "Answer again, in English only.")
    achados = _pede_escrita(brief) if brief else []
    if achados:
        problemas.append(
            "Your previous answer asked for writing in the image "
            f"({', '.join(achados)}). Describe a scene where nothing displays "
            "writing of any kind. Replace those elements with light, texture "
            "or landscape."
        )
    if problemas:
        segunda = _pedir_brief(lyrics, model, host,
                               reforco="\n\n" + " ".join(problemas))
        # So aceita a segunda se ela for melhor: uma retentativa pior nao ajuda.
        if segunda and not _pede_escrita(segunda) and _parece_ingles(segunda):
            brief = segunda

    if not brief:
        raise ValueError("brief vazio devolvido pelo Ollama")
    return brief


def image_prompt(brief: str) -> str:
    """Brief + regras fixas. As regras vao literais, nao confiadas ao LLM."""
    return f"{brief.strip()}, {IMAGE_RULES}"


def _inject_prompt(workflow_text: str, prompt: str) -> dict:
    """Substitui os marcadores no TEXTO do template e devolve o grafo parseado.

    Marcador, nunca id de no: o id do CLIPTextEncode positivo muda a cada
    reexport da GUI, e errar o id derruba o estagio em silencio (KeyError
    engolido pelo except do 08b -> fundo chapado permanente). O template diz
    onde o prompt entra; o codigo nao adivinha.

    %prompt% vem DENTRO de aspas no template, entao entra escapado e sem aspas
    proprias — json.dumps(...)[1:-1]. Um brief com aspas ou barra invertida
    corromperia o JSON de outro jeito.
    %seed% e um numero CRU (sem aspas), por isso a substituicao e no texto e
    nao no dict: `"seed": %seed%` nem parseia como JSON antes da troca.
    """
    if "%prompt%" not in workflow_text:
        raise ValueError(
            "o template do workflow tem de conter o marcador %prompt% no valor "
            "do prompt positivo — um export cru da GUI do ComfyUI nao serve "
            "sem marcar; ver README, secao Estagio 11"
        )
    # %seed% primeiro: o prompt e texto livre escrito por um LLM, e trocar o
    # prompt antes deixaria um "%seed%" vindo do brief ser substituido por um
    # numero. Na outra ordem o valor injetado do seed e so digitos, entao nao
    # pode conter "%prompt%". Uma ordem e segura, a outra nao.
    texto = workflow_text.replace("%seed%", str(random.randrange(0, 2 ** 32)))
    texto = texto.replace("%prompt%", json.dumps(prompt)[1:-1])
    return json.loads(texto)


def _bust_cache(workflow: dict) -> int:
    """Sufixa um nonce unico em TODO filename_prefix. Devolve quantos mudou.

    Reenviar um grafo identico faz o ComfyUI responder `execution_cached` com
    `outputs: {}` — e o 08b cai no fundo chapado em silencio, para sempre
    naquela musica (renderizar a mesma cancao duas vezes perdia a ilustracao
    sem nenhuma pista). Sujar o prefixo na raiz e o que o ComfyUI de fato
    considera na chave de cache.

    Varre TODOS os nos: um grafo pode ter mais de um SaveImage, e supor um so
    deixaria os outros cacheados.
    """
    nonce = uuid.uuid4().hex[:8]
    mudados = 0
    for node in workflow.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if isinstance(inputs, dict) and isinstance(inputs.get("filename_prefix"), str):
            inputs["filename_prefix"] = f"{inputs['filename_prefix']}_{nonce}"
            mudados += 1
    # ponytail: grafo sem nenhum filename_prefix devolve 0 e segue — nao da
    # para quebrar o cache do que nao salva arquivo. Quem chama nao trata:
    # o sintoma vira outputs vazio, e ai o _diagnostico abaixo e que fala.
    return mudados


def _diagnostico(entry: dict) -> str:
    """O que o ComfyUI reclamou, em uma linha legivel.

    `status=success` com outputs vazio e comum: um no que falha validacao
    derruba as saidas em cascata e o /history segue reportando sucesso. O
    diagnostico util esta no objeto `status`, nao no status_str. Tudo por
    .get(): mudanca de esquema tem de degradar para mensagem pobre, nunca
    para KeyError dentro do caminho de erro.
    """
    status = entry.get("status") or {}
    partes = [str(status.get("status_str") or "")]
    for m in status.get("messages") or []:
        partes.append(str(m))
    texto = " | ".join(p for p in partes if p)
    return (texto[:600] if texto else "sem diagnostico no /history")


def resolve_comfy_host() -> str:
    """Descobre onde o ComfyUI esta ouvindo. Levanta nomeando o que tentou.

    1. COMFYUI_URL, se setada — literal, sem sondar.
    2. senao sonda COMFY_PORTS em ordem contra /system_stats.
    3. nenhuma responde -> erro que nomeia TODAS as candidatas, para o aviso
       do 08b dizer "nenhum ComfyUI em 8188/8000/8001" e nao um recusa de
       conexao pelado apontando so a primeira.
    """
    url = os.environ.get(COMFY_ENV_VAR)
    if url:
        return url.rstrip("/")
    for porta in COMFY_PORTS:
        alvo = f"http://127.0.0.1:{porta}"
        try:
            with urllib.request.urlopen(f"{alvo}/system_stats",
                                        timeout=COMFY_PROBE_SECONDS):
                return alvo
        except Exception:
            continue
    raise RuntimeError(
        "nenhum ComfyUI respondeu em "
        + "/".join(str(p) for p in COMFY_PORTS)
        + f" — abra o app ou aponte {COMFY_ENV_VAR} para a URL dele"
    )


def generate_image(prompt: str, out_path: Path, workflow_path: Path,
                   host: str = None) -> Path:
    """Enfileira no ComfyUI, espera terminar e copia o PNG para out_path.

    host=None resolve por COMFYUI_URL/sondagem; um host explicito pula tudo."""
    workflow = _inject_prompt(
        Path(workflow_path).read_text(encoding="utf-8"), prompt)
    _bust_cache(workflow)
    # Depois do inject: template sem marcador falha sem sondar porta nenhuma.
    host = host or resolve_comfy_host()
    body = _post_json(f"{host}/prompt", {"prompt": workflow}, timeout=30)
    prompt_id = body["prompt_id"]

    deadline = time.monotonic() + COMFY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{host}/history/{prompt_id}", timeout=30) as r:
            hist = json.loads(r.read())
        if prompt_id in hist:
            entry = hist[prompt_id] or {}
            imgs = [
                img
                for node in (entry.get("outputs") or {}).values()
                for img in (node or {}).get("images", [])
            ]
            if not imgs:
                raise RuntimeError(
                    "ComfyUI terminou sem produzir imagem — "
                    + _diagnostico(entry))
            img = imgs[0]
            # subfolder vem preenchido quando o filename_prefix do SaveImage
            # tem "/" (ex.: "karaoke/bg"); ignora-lo faz a copia errar o alvo.
            src = (COMFY_OUTPUT_ROOT / img.get("type", "output")
                   / img.get("subfolder", "") / img["filename"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out_path)
            return out_path
        time.sleep(COMFY_POLL_SECONDS)

    raise TimeoutError(f"ComfyUI nao terminou em {COMFY_TIMEOUT_SECONDS}s")
