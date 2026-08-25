"""
Gera a ilustracao de fundo a partir da letra, tudo local.

Brief:  Ollama  (llama3.2:3b, saida estruturada)
Imagem: ComfyUI (z_image_turbo, HTTP)

Nada aqui pode derrubar o job: quem chama trata excecao e cai no fundo chapado.
"""
import json
import random
import shutil
import time
import uuid
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://127.0.0.1:11434"
COMFY_HOST = "http://127.0.0.1:8188"   # ponytail: confirmar com o app aberto
BRIEF_MODEL = "llama3.2:3b"            # qwen3:4b devolve as proprias instrucoes

COMFY_OUTPUT_ROOT = Path("C:/ComfyUI")
COMFY_POLL_SECONDS = 2
COMFY_TIMEOUT_SECONDS = 300

_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {"brief": {"type": "string"}},
    "required": ["brief"],
}

_BRIEF_SYSTEM = (
    "You write visual briefs for karaoke video background illustrations. "
    "Read the lyrics and write ONE English paragraph (max 55 words) describing an "
    "illustration: scene, palette, texture, mood. Hard rules: no text, letters or "
    "words anywhere in the image; the centre of the composition stays dark and "
    "uncluttered; 16:9."
)

IMAGE_RULES = (
    "illustration, painterly, no text, no letters, no words, no watermark, "
    "dark uncluttered centre, cinematic lighting, 16:9"
)


def _post_json(url: str, payload: dict, timeout: int):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def build_brief(lyrics: str, model: str = BRIEF_MODEL, host: str = OLLAMA_HOST) -> str:
    """Letra -> um paragrafo de direcao visual. Levanta em caso de falha."""
    body = _post_json(
        f"{host}/api/chat",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _BRIEF_SYSTEM},
                {"role": "user", "content": f"LYRICS:\n{lyrics}"},
            ],
            "stream": False,
            "think": False,
            "format": _BRIEF_SCHEMA,
            "options": {"temperature": 0.8},
        },
        timeout=300,
    )
    brief = json.loads(body["message"]["content"])["brief"].strip()
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


def generate_image(prompt: str, out_path: Path, workflow_path: Path,
                   host: str = COMFY_HOST) -> Path:
    """Enfileira no ComfyUI, espera terminar e copia o PNG para out_path."""
    workflow = _inject_prompt(
        Path(workflow_path).read_text(encoding="utf-8"), prompt)
    _bust_cache(workflow)
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
