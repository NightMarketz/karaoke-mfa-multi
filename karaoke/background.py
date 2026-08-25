"""
Gera a ilustracao de fundo a partir da letra, tudo local.

Brief:  Ollama  (llama3.2:3b, saida estruturada)
Imagem: ComfyUI (z_image_turbo, HTTP)

Nada aqui pode derrubar o job: quem chama trata excecao e cai no fundo chapado.
"""
import copy
import json
import shutil
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://127.0.0.1:11434"
COMFY_HOST = "http://127.0.0.1:8188"   # ponytail: confirmar com o app aberto
BRIEF_MODEL = "llama3.2:3b"            # qwen3:4b devolve as proprias instrucoes

COMFY_PROMPT_NODE = "6"        # id do CLIPTextEncode positivo — ver Task 4 Step 1
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


def _inject_prompt(workflow: dict, prompt: str, node_id: str = COMFY_PROMPT_NODE) -> dict:
    """Copia o workflow com o prompt no no positivo. Nao muta o original."""
    if node_id not in workflow:
        raise KeyError(f"no {node_id} ausente do workflow — reexportar em formato API")
    wf = copy.deepcopy(workflow)
    wf[node_id]["inputs"]["text"] = prompt
    return wf


def generate_image(prompt: str, out_path: Path, workflow_path: Path,
                   host: str = COMFY_HOST) -> Path:
    """Enfileira no ComfyUI, espera terminar e copia o PNG para out_path."""
    workflow = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
    body = _post_json(f"{host}/prompt",
                      {"prompt": _inject_prompt(workflow, prompt)}, timeout=30)
    prompt_id = body["prompt_id"]

    deadline = time.monotonic() + COMFY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{host}/history/{prompt_id}", timeout=30) as r:
            hist = json.loads(r.read())
        if prompt_id in hist:
            imgs = [
                img
                for node in hist[prompt_id]["outputs"].values()
                for img in node.get("images", [])
            ]
            if not imgs:
                raise RuntimeError("ComfyUI terminou sem produzir imagem")
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
