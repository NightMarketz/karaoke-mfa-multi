# Fundo de ilustração gerado localmente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar o fundo preto chapado do vídeo de karaokê por uma ilustração gerada localmente a partir da letra, com deriva lenta e pulso nos onsets do instrumental — reparando o Step 09, que hoje não roda.

**Architecture:** Lógica testável entra em `karaoke/` (padrão do `ass_builder.py`); os `scripts/` ficam como invólucros finos de CLI. O brief sai do Ollama e a imagem do ComfyUI, ambos por HTTP com `urllib` da stdlib. O ffmpeg recebe o PNG com `-loop 1` e um arquivo `sendcmd` que dirige o `crop`.

**Tech Stack:** Python 3.11 (stdlib `urllib`/`json`/`wave`), numpy (já em uso), ffmpeg 8.1, ComfyUI Desktop (HTTP), Ollama (HTTP), pytest.

## Global Constraints

- **Nenhuma dependência Python nova.** Só stdlib + numpy, que já está no pipeline.
- **Nada de rede paga.** Ollama e ComfyUI são locais.
- **Falha de fundo nunca derruba o job.** Sem PNG → fundo `#08090f` chapado, exit 0.
- **A letra crua não vai para o gerador de imagem** — só o brief.
- **Regras fixas de imagem** (sufixo literal, não confiado ao LLM): sem texto/letras/palavras; centro escuro e limpo; 16:9; lado maior ≤ 1024.
- **Modelo de imagem:** `z_image_turbo_bf16.safetensors` (Apache 2.0). **Nunca** `flux1-krea-dev` — licença não comercial.
- **Modelo de brief:** `llama3.2:3b`. Medido: 4,8 s, brief usável. `qwen3:4b` foi testado e devolve as próprias instruções — não usar.
- **No ffmpeg, `scale` vem DEPOIS do `crop`.** Sem isso o `sendcmd` não produz efeito visível (verificado).
- Commits em português, imperativo, prefixo `feat:`/`fix:`/`test:`.

## Fatos medidos que o plano assume

| fato | como foi verificado |
|---|---|
| `09_video_rendering.py` usa 12 acessores `kpaths`, **6 ausentes** | resolvido contra o módulo real |
| Primeiro ausente: `adlibs_json` na linha 392 → estoura antes de escrever o ASS | leitura do call site |
| Ausentes também em `master`/`origin/master`/`main`/`origin/main` (0/6) | `git show <ref>:karaoke/paths.py` |
| `crop` tem `w`/`h`/`x`/`y` comandáveis (flag `T`); `sendcmd` existe | `ffmpeg -h filter=crop`, ffmpeg 8.1 |
| `sendcmd` só age se houver `scale` depois do `crop` | render pareado com/sem comando sobre imagem estática, 75 frames cada |
| Ollama vivo em `127.0.0.1:11434` | `netstat` |
| ComfyUI **não** estava rodando — porta 8188 não confirmada | `netstat` |

## File Structure

| arquivo | responsabilidade |
|---|---|
| `karaoke/paths.py` (modificar) | acessores de caminho ausentes + `background_png()` |
| `karaoke/bounce.py` (criar) | onsets → texto do `sendcmd`. Sem I/O de rede. |
| `karaoke/background.py` (criar) | brief (Ollama) + imagem (ComfyUI). HTTP isolado aqui. |
| `karaoke/render_cmd.py` (criar) | monta a lista de args do ffmpeg. Sem subprocess. |
| `scripts/08b_background_image.py` (criar) | CLI fino: `--job-id` → chama `karaoke.background` |
| `scripts/09_video_rendering.py` (modificar) | bloco de render reparado, usando `render_cmd` |
| `run_pipeline.py` (modificar) | registra o estágio `08b` |
| `scripts/08_render_video.py` (deletar) | órfão quebrado |
| `tests/test_paths_contract.py`, `tests/test_bounce.py`, `tests/test_background.py`, `tests/test_render_cmd.py` | cercas |

---

### Task 1: Reparar os acessores de `karaoke/paths.py`

**Files:**
- Modify: `karaoke/paths.py`
- Modify: `scripts/09_video_rendering.py:395`
- Test: `tests/test_paths_contract.py` (criar)

**Interfaces:**
- Consumes: nada.
- Produces: `kpaths.adlibs_json(job_id) -> Path`, `kpaths.input_video(job_id) -> Path`, `kpaths.input_thumb(job_id) -> Path`, `kpaths.output_video(job_id) -> Path`, `kpaths.input_job_dir(job_id) -> Path`, `kpaths.background_png(job_id) -> Path`. Todos recebem `job_id: str` e devolvem `pathlib.Path` absoluto.

- [ ] **Step 1: Escrever o teste que falha**

Esta é a cerca principal da tarefa: resolve **todo** `kpaths.X` referenciado pelos scripts de render contra o módulo real, e diz quantos examinou.

```python
# tests/test_paths_contract.py
"""Contrato: todo kpaths.X citado nos scripts de render tem de existir."""
import io
import re
from pathlib import Path

import pytest

import karaoke.paths as kpaths

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["scripts/09_video_rendering.py", "scripts/08b_background_image.py"]


def _referenced(script_rel):
    src = io.open(ROOT / script_rel, encoding="utf-8").read()
    return sorted(set(re.findall(r"kpaths\.([a-zA-Z_0-9]+)", src)))


@pytest.mark.parametrize("script_rel", SCRIPTS)
def test_todo_acessor_citado_existe(script_rel):
    if not (ROOT / script_rel).exists():
        pytest.skip(f"{script_rel} ainda nao existe — criado na Task 4")
    names = _referenced(script_rel)
    assert names, f"nenhum kpaths.X encontrado em {script_rel} — teste inutil"
    missing = [n for n in names if not hasattr(kpaths, n)]
    assert not missing, (
        f"{script_rel}: {len(missing)} de {len(names)} acessores ausentes: {missing}"
    )


def test_acessores_novos_devolvem_path_absoluto():
    novos = [
        "adlibs_json", "input_video", "input_thumb",
        "output_video", "input_job_dir", "background_png",
    ]
    for name in novos:
        p = getattr(kpaths, name)("job_teste")
        assert isinstance(p, Path), f"{name} nao devolveu Path"
        assert p.is_absolute(), f"{name} devolveu caminho relativo: {p}"
        assert "job_teste" in str(p), f"{name} ignorou o job_id: {p}"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_paths_contract.py -v`
Expected: FAIL. O caso de `09_video_rendering.py` acusa 6 ausentes de 12; o segundo teste falha com `AttributeError`. O caso de `08b` sai como SKIP — o arquivo só nasce na Task 4, e a Task 4 Step 7 exige que ele deixe de ser pulado.

- [ ] **Step 3: Repontar o que já tem equivalente**

`kpaths.lyrics_path` já existe e aponta para a mesma letra. Em `scripts/09_video_rendering.py:395`, trocar:

```python
    lyrics_txt           = kpaths.lyrics_txt(job_id)
```
por:
```python
    lyrics_txt           = kpaths.lyrics_path(job_id)
```

Não criar `lyrics_txt` em `paths.py`. Um nome por conceito.

- [ ] **Step 4: Descobrir onde o Demucs grava de fato**

Antes de escrever `input_job_dir`, confirmar o layout real de `02_separation/htdemucs/<nome>/no_vocals.wav`. O acessor tem de apontar para onde o estágio **já grava**, não para um layout inventado.

Run: `grep -nE "htdemucs|no_vocals|output|--out|-o " scripts/02_vocal_isolation.py`

- [ ] **Step 5: Adicionar os acessores**

No fim de `karaoke/paths.py`, seguindo a convenção `job_root(job_id) / ...` das 31 funções existentes:

```python
# --- Render / fundo ---

def adlibs_json(job_id: str) -> Path:
    """Timings de adlibs gerados pelo Step 03c/07."""
    return alignment_dir(job_id) / "adlibs_timing.json"

def input_job_dir(job_id: str) -> Path:
    """Diretorio de entrada do job — o Demucs usa o .name dele como subpasta."""
    return input_dir(job_id)

def input_video(job_id: str) -> Path:
    """Video de fundo fornecido pelo usuario (opcional)."""
    return input_dir(job_id) / "background.mp4"

def input_thumb(job_id: str) -> Path:
    """Imagem de fundo fornecida pelo usuario (opcional)."""
    return input_dir(job_id) / "background.png"

def background_png(job_id: str) -> Path:
    """Ilustracao gerada pelo Step 08b."""
    return step_output(job_id, "08_background") / "background.png"

def output_video(job_id: str) -> Path:
    """MP4 final. Alias do final_video ja existente."""
    return final_video(job_id)
```

Se o Step 4 mostrar layout diferente para o Demucs, ajustar `input_job_dir` conforme o achado e anotar no commit.

- [ ] **Step 6: Rodar e ver passar**

Run: `python -m pytest tests/test_paths_contract.py::test_acessores_novos_devolvem_path_absoluto -v`
Expected: PASS.

Run: `python -m pytest "tests/test_paths_contract.py::test_todo_acessor_citado_existe[scripts/09_video_rendering.py]" -v`
Expected: PASS.

- [ ] **Step 7: Controle negativo**

Renomear temporariamente `adlibs_json` para `adlibs_json_x` em `paths.py` e rodar o teste de novo.
Expected: **FAIL**, citando `['adlibs_json']` e o total examinado. Desfazer a renomeação.
Cerca que nunca foi vista vermelha não é cerca.

- [ ] **Step 8: Commit**

```bash
git add karaoke/paths.py scripts/09_video_rendering.py tests/test_paths_contract.py
git commit -m "fix: adiciona acessores kpaths ausentes que quebravam o Step 09"
```

---

### Task 2: `karaoke/bounce.py` — onsets viram script do sendcmd

**Files:**
- Create: `karaoke/bounce.py`
- Test: `tests/test_bounce.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `build_sendcmd(onsets, base_w: int, base_h: int, pulse: float = 0.03, decay: float = 0.18) -> str`
  - `onsets_from_wav(wav_path: Path) -> list`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_bounce.py
"""Unit tests para karaoke.bounce. Sem I/O de audio, sem subprocess."""
import re

import pytest

from karaoke.bounce import build_sendcmd


def test_uma_dupla_de_comandos_por_onset():
    onsets = [0.5, 1.25, 2.0]
    txt = build_sendcmd(onsets, 1408, 792)
    linhas = [l for l in txt.splitlines() if l.strip()]
    # cada onset gera 2 linhas: o pulso e o retorno
    assert len(linhas) == len(onsets) * 2, (
        f"{len(linhas)} linhas para {len(onsets)} onsets"
    )


def test_lista_vazia_e_erro_nao_arquivo_vazio():
    # sendcmd vazio renderiza verde e nao faz nada — falso positivo silencioso
    with pytest.raises(ValueError, match="nenhum onset"):
        build_sendcmd([], 1408, 792)


def test_pulso_encolhe_o_crop_e_o_retorno_restaura():
    txt = build_sendcmd([1.0], 1408, 792, pulse=0.05)
    linhas = [l for l in txt.splitlines() if l.strip()]
    assert linhas[0].startswith("1.000 ")
    assert "crop w 1336" in linhas[0]      # 1408*0.95 = 1337.6 -> par para baixo
    assert "crop h 752" in linhas[0]       # 792*0.95  = 752.4  -> par para baixo
    assert "crop w 1408" in linhas[1]      # retorno ao tamanho cheio
    assert "crop h 792" in linhas[1]


def test_dimensoes_do_pulso_sao_pares():
    # libx264 rejeita dimensao impar em yuv420p
    txt = build_sendcmd([0.5, 1.0, 1.5], 1408, 792, pulse=0.037)
    pares = re.findall(r"crop w (\d+), crop h (\d+)", txt)
    assert pares, "nenhum comando de crop encontrado — teste inutil"
    for w, h in pares:
        assert int(w) % 2 == 0, f"largura impar: {w}"
        assert int(h) % 2 == 0, f"altura impar: {h}"


def test_onsets_muito_proximos_nao_se_sobrepoem():
    # decay=0.18: o retorno de 1.0 cairia em 1.18, depois do onset 1.05
    txt = build_sendcmd([1.0, 1.05], 1408, 792, decay=0.18)
    tempos = [float(l.split(" ", 1)[0]) for l in txt.splitlines() if l.strip()]
    assert tempos == sorted(tempos), f"comandos fora de ordem: {tempos}"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_bounce.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'karaoke.bounce'`.

- [ ] **Step 3: Implementar**

```python
# karaoke/bounce.py
"""
Converte onsets de audio no script de comandos do filtro sendcmd do FFmpeg.

O crop e comandado em runtime: no onset ele encolhe (zoom in), e logo depois
volta ao tamanho cheio. O `scale` que vem DEPOIS do crop na cadeia e o que
mantem a resolucao de saida fixa — sem ele o comando nao produz efeito visivel.

Sintaxe do arquivo sendcmd (verificada no ffmpeg 8.1):
    TEMPO alvo comando valor, alvo comando valor;
"""
import wave
from pathlib import Path

import numpy as np

# Espelha scripts/05c_onset_dtw_align.py — mesma deteccao, mesmo comportamento.
ONSET_THRESHOLD = 0.008
MIN_GAP = 0.08
ENERGY_MIN = 0.02
WINDOW_MS = 25
HOP_MS = 10


def _par(n: float) -> int:
    """Arredonda para baixo ate um inteiro par (libx264 rejeita impar)."""
    return int(n) // 2 * 2


def build_sendcmd(onsets, base_w: int, base_h: int,
                  pulse: float = 0.03, decay: float = 0.18) -> str:
    """
    Texto do arquivo sendcmd: um pulso por onset, com retorno ao tamanho cheio.

    pulse: fracao de encolhimento do crop no onset (0.03 = 3%).
    decay: segundos ate voltar ao tamanho cheio.
    """
    if len(onsets) == 0:
        raise ValueError(
            "nenhum onset detectado — sendcmd vazio nao produz movimento nenhum"
        )

    pw, ph = _par(base_w * (1 - pulse)), _par(base_h * (1 - pulse))
    fw, fh = _par(base_w), _par(base_h)

    eventos = []
    ordenados = sorted(float(t) for t in onsets)
    for i, t in enumerate(ordenados):
        eventos.append((t, pw, ph))
        volta = t + decay
        # ponytail: se o proximo onset chega antes do retorno, o retorno e
        # descartado — o proximo pulso ja reassume. Mantem os comandos em ordem
        # crescente, que e o que o sendcmd exige.
        if i + 1 >= len(ordenados) or volta < ordenados[i + 1]:
            eventos.append((volta, fw, fh))

    return "".join(f"{t:.3f} crop w {w}, crop h {h};\n" for t, w, h in eventos)


def onsets_from_wav(wav_path: Path) -> list:
    """RMS frame a frame + derivada, igual ao 05c_onset_dtw_align.py."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = audio.astype(np.float32)
    audio /= np.abs(audio).max() + 1e-8

    hop = int(sr * HOP_MS / 1000)
    win = int(sr * WINDOW_MS / 1000)
    rms = np.array([
        float(np.sqrt(np.mean(audio[i:i + win] ** 2)))
        for i in range(0, len(audio) - win, hop)
    ])
    frame_dur = hop / sr

    onsets, last = [], -1.0
    for i, d in enumerate(np.diff(rms)):
        t = i * frame_dur
        if d > ONSET_THRESHOLD and rms[i + 1] > ENERGY_MIN and (t - last) > MIN_GAP:
            onsets.append(t)
            last = t
    return onsets
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_bounce.py -v`
Expected: PASS, 5 testes.

Se `test_pulso_encolhe_o_crop_e_o_retorno_restaura` falhar por 1 pixel, conferir o arredondamento par de `_par` e corrigir o **teste** para o valor que `_par` produz — a regra que importa é ser par, não o valor exato.

- [ ] **Step 5: Controle negativo**

Em `build_sendcmd`, trocar `if len(onsets) == 0:` por `if False:` e rodar de novo.
Expected: **FAIL** em `test_lista_vazia_e_erro_nao_arquivo_vazio`. Desfazer.

- [ ] **Step 6: Commit**

```bash
git add karaoke/bounce.py tests/test_bounce.py
git commit -m "feat: converte onsets do instrumental em script sendcmd do ffmpeg"
```

---

### Task 3: `karaoke/background.py` — brief pelo Ollama

**Files:**
- Create: `karaoke/background.py`
- Test: `tests/test_background.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `build_brief(lyrics: str, model: str = BRIEF_MODEL, host: str = OLLAMA_HOST) -> str`
  - `image_prompt(brief: str) -> str`
  - Constantes `OLLAMA_HOST`, `COMFY_HOST`, `BRIEF_MODEL`, `IMAGE_RULES`.

- [ ] **Step 1: Escrever o teste que falha**

O HTTP é dublado — o teste não depende do Ollama estar de pé.

```python
# tests/test_background.py
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_background.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'karaoke.background'`.

- [ ] **Step 3: Implementar**

Este código é a versão já validada contra o Ollama real (`/api/chat` + `format`, `llama3.2:3b`, 4,8 s). **Não trocar por `/api/generate`**: naquele endpoint o modelo devolve raciocínio em prosa e a saída fica imprestável — foi medido.

```python
# karaoke/background.py
"""
Gera a ilustracao de fundo a partir da letra, tudo local.

Brief:  Ollama  (llama3.2:3b, saida estruturada)
Imagem: ComfyUI (z_image_turbo, HTTP)

Nada aqui pode derrubar o job: quem chama trata excecao e cai no fundo chapado.
"""
import json
import urllib.request

OLLAMA_HOST = "http://127.0.0.1:11434"
COMFY_HOST = "http://127.0.0.1:8188"   # ponytail: confirmar com o app aberto
BRIEF_MODEL = "llama3.2:3b"            # qwen3:4b devolve as proprias instrucoes

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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_background.py -v`
Expected: PASS, 4 testes.

- [ ] **Step 5: Verificação contra o Ollama real**

Run: `python -c "from karaoke.background import build_brief, image_prompt; b = build_brief('Andei por caminhos tortos, vi o sol nascer no mar'); print(b); print('---'); print(image_prompt(b))"`
Expected: um parágrafo em inglês descrevendo a cena, e o prompt com as regras coladas no fim. Se o Ollama não estiver de pé, `URLError` — aceitável aqui, é verificação manual, não teste.

- [ ] **Step 6: Commit**

```bash
git add karaoke/background.py tests/test_background.py
git commit -m "feat: gera brief visual da letra via Ollama local"
```

---

### Task 4: Imagem pelo ComfyUI + `scripts/08b`

**Files:**
- Modify: `karaoke/background.py`
- Create: `scripts/08b_background_image.py`
- Create: `config/comfy_workflow.json`
- Modify: `tests/test_background.py`

**Interfaces:**
- Consumes: `build_brief`, `image_prompt`, `_post_json` (Task 3); `kpaths.background_png`, `kpaths.lyrics_path` (Task 1).
- Produces: `_inject_prompt(workflow: dict, prompt: str, node_id: str) -> dict` e `generate_image(prompt: str, out_path: Path, workflow_path: Path, host: str = COMFY_HOST) -> Path`.

- [ ] **Step 1: Exportar o workflow do ComfyUI**

Passo manual, feito uma vez. Abrir o ComfyUI Desktop, montar o grafo mínimo com `z_image_turbo_bf16.safetensors` (4–10 passos, 1024×576), e exportar em **Workflow → Export (API)**. Salvar como `config/comfy_workflow.json`.

Anotar o **id do nó** `CLIPTextEncode` positivo — vai em `COMFY_PROMPT_NODE`. Já existe um exemplo de formato API em `C:/ComfyUI/user/default/workflows/H24_api.json`: serve de referência do **formato**, não do conteúdo.

Confirmar a porta com o app aberto:
Run: `netstat -ano -p tcp | grep LISTENING | grep 8188`
Se for outra, ajustar `COMFY_HOST` em `karaoke/background.py`.

- [ ] **Step 2: Escrever o teste que falha**

Acrescentar a `tests/test_background.py`:

```python
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
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `python -m pytest tests/test_background.py -v`
Expected: FAIL com `ImportError: cannot import name '_inject_prompt'`.

- [ ] **Step 4: Implementar**

Acrescentar a `karaoke/background.py` (os imports vão no topo do arquivo, junto dos existentes):

```python
import copy
import shutil
import time
from pathlib import Path

COMFY_PROMPT_NODE = "6"        # id do CLIPTextEncode positivo — ver Task 4 Step 1
COMFY_OUTPUT_ROOT = Path("C:/ComfyUI")
COMFY_POLL_SECONDS = 2
COMFY_TIMEOUT_SECONDS = 300


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
            src = COMFY_OUTPUT_ROOT / img.get("type", "output") / img["filename"]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out_path)
            return out_path
        time.sleep(COMFY_POLL_SECONDS)

    raise TimeoutError(f"ComfyUI nao terminou em {COMFY_TIMEOUT_SECONDS}s")
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_background.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 6: Escrever o CLI**

```python
# scripts/08b_background_image.py
"""
08b_background_image.py — Gera a ilustracao de fundo a partir da letra.

Inputs  (via --job-id):
  work/jobs/{job_id}/input/lyrics.txt

Outputs (via --job-id):
  work/jobs/{job_id}/08_background/background.png

Falha NUNCA derruba o job: sem PNG, o Step 09 usa fundo chapado.
"""
import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import karaoke.paths as kpaths
from karaoke.background import build_brief, generate_image, image_prompt

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

WORKFLOW = Path(__file__).resolve().parent.parent / "config" / "comfy_workflow.json"


def _progress(pct: int, msg: str = ""):
    print(f"PROGRESS: {pct} | {msg}" if msg else f"PROGRESS: {pct}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Gera ilustracao de fundo (local)")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    print("=== Step 08b: Background Illustration ===")
    out = kpaths.background_png(args.job_id)

    if out.exists():
        print(f"  Cache encontrado ({out.name}) — pulando geracao.")
        _progress(100, "Fundo em cache.")
        return

    try:
        _progress(10, "Lendo letra...")
        lyrics = kpaths.lyrics_path(args.job_id).read_text(encoding="utf-8")

        _progress(25, "Gerando brief visual (Ollama)...")
        brief = build_brief(lyrics)
        print(f"  Brief: {brief}")

        _progress(45, "Gerando ilustracao (ComfyUI)...")
        generate_image(image_prompt(brief), out, WORKFLOW)

        size_kb = out.stat().st_size / 1024
        _progress(100, f"Fundo gerado — {size_kb:.0f} KB")
        print(f"OK Fundo salvo em: {out}")
    except Exception as e:
        # Fundo e enfeite. Sem ele o Step 09 usa #08090f e o job segue.
        print(f"  AVISO: fundo nao gerado ({type(e).__name__}: {e})")
        print("  O video sera renderizado com fundo chapado.")
        _progress(100, "Sem fundo — seguindo com fundo chapado.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Verificar o contrato de paths**

Run: `python -m pytest tests/test_paths_contract.py -v`
Expected: PASS nos dois scripts, **0 skipped**. O caso de `08b` era SKIP desde a Task 1; agora que o arquivo existe ele tem de rodar de verdade. Se continuar SKIP, o caminho em `SCRIPTS` não bate com o arquivo criado — corrigir antes de seguir.

- [ ] **Step 8: Commit**

```bash
git add karaoke/background.py scripts/08b_background_image.py config/comfy_workflow.json tests/test_background.py
git commit -m "feat: gera ilustracao de fundo via ComfyUI local com cache e fallback"
```

---

### Task 5: Reparar o render do Step 09 e plugar o fundo

**Files:**
- Create: `karaoke/render_cmd.py`
- Modify: `scripts/09_video_rendering.py:516-551`
- Test: `tests/test_render_cmd.py`

**Interfaces:**
- Consumes: `kpaths` (Task 1), `karaoke.bounce.build_sendcmd` e `onsets_from_wav` (Task 2).
- Produces: `build_render_cmd(bg_png, audio_inputs, ass_path, out_mp4, duration, sendcmd_path) -> list` e as constantes `WORK_W`, `WORK_H`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_render_cmd.py
"""Contrato do comando ffmpeg. Monta a lista de args, nao roda o encoder."""
from pathlib import Path

from karaoke.render_cmd import build_render_cmd

ASS = Path("/tmp/karaoke.ass")
OUT = Path("/tmp/out.mp4")
INST = Path("/tmp/no_vocals.wav")
VOX = Path("/tmp/vocals.wav")
BG = Path("/tmp/bg.png")
SC = Path("/tmp/bounce.txt")


def _fc(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_com_fundo_usa_loop_e_sendcmd():
    cmd = build_render_cmd(BG, [INST, VOX], ASS, OUT, 210.0, SC)
    assert "-loop" in cmd and cmd[cmd.index("-loop") + 1] == "1"
    assert "sendcmd" in _fc(cmd)


def test_scale_vem_depois_do_crop():
    # Verificado empiricamente: sem scale apos o crop o sendcmd nao tem efeito.
    fc = _fc(build_render_cmd(BG, [INST, VOX], ASS, OUT, 210.0, SC))
    assert fc.index("crop=") < fc.index("scale=1280:720"), f"ordem errada: {fc}"


def test_sem_fundo_cai_no_chapado_e_sem_sendcmd():
    cmd = build_render_cmd(None, [INST, VOX], ASS, OUT, 210.0, None)
    assert any("color=c=#08090f" in a for a in cmd)
    assert "sendcmd" not in _fc(cmd)
    assert "-loop" not in cmd


def test_duracao_sempre_presente():
    # Sem -t, imagem estatica com -loop 1 gera video infinito.
    for bg, sc in ((BG, SC), (None, None)):
        cmd = build_render_cmd(bg, [INST, VOX], ASS, OUT, 210.0, sc)
        assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "210.0"


def test_yuv420p_sempre_presente():
    for bg, sc in ((BG, SC), (None, None)):
        assert "format=yuv420p" in _fc(
            build_render_cmd(bg, [INST, VOX], ASS, OUT, 210.0, sc))


def test_caminho_do_windows_tem_dois_pontos_escapado():
    # Medido contra o ffmpeg 8.1 real via subprocess.run, caminho do Windows
    # com e sem espaco: sem escape o encoder falha ("Invalid argument"); uma
    # barra invertida funciona (rc=0) e e a forma que usamos. Os demais
    # testes deste arquivo usam caminhos /tmp/ sem dois-pontos e nao
    # pegariam uma regressao aqui.
    win_ass = Path(r"C:\jobs\k.ass")
    win_sc = Path(r"C:\jobs\bounce.txt")
    fc = _fc(build_render_cmd(BG, [INST, VOX], win_ass, OUT, 210.0, win_sc))
    assert "subtitles='C\\:/jobs/k.ass'" in fc, fc
    assert "sendcmd=f='C\\:/jobs/bounce.txt'" in fc, fc
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_render_cmd.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'karaoke.render_cmd'`.

- [ ] **Step 3: Implementar**

```python
# karaoke/render_cmd.py
"""Monta o comando ffmpeg do render final. Sem subprocess — so a lista de args."""
from pathlib import Path

FLAT_BG = "color=c=#08090f:s=1280x720"
WORK_W, WORK_H = 1408, 792      # 10% acima de 1280x720: folga para o zoom
OUT_W, OUT_H = 1280, 720


def _escape(p) -> str:
    """Caminho seguro dentro de um filtergraph do ffmpeg.

    Barra normal, dois-pontos escapado, e o valor entre aspas simples no
    filtro. Medido contra o ffmpeg 8.1 real via subprocess.run (lista de
    args, sem shell), com caminho do Windows com e sem espaco: SEM escape
    falha ("Invalid argument"); uma barra invertida e duas funcionam as
    duas (rc=0). Usamos uma.

    Cuidado ao reverificar: medir isso pela linha de comando do bash da
    resultado diferente — as aspas do shell comem um nivel de barra antes
    do ffmpeg ver. So vale a medicao pelo caminho de producao.
    """
    return str(p).replace("\\", "/").replace(":", "\\:")


def build_render_cmd(bg_png, audio_inputs, ass_path: Path, out_mp4: Path,
                     duration: float, sendcmd_path) -> list:
    """
    bg_png:       Path do PNG de fundo, ou None para o fundo chapado.
    audio_inputs: [instrumental, vocais] — mixados com amix.
    sendcmd_path: Path do bounce.txt, ou None para nenhum movimento.
    """
    cmd = ["ffmpeg", "-y", "-hide_banner"]

    if bg_png is not None:
        cmd += ["-loop", "1", "-i", str(bg_png)]
    else:
        cmd += ["-f", "lavfi", "-i", FLAT_BG]

    for a in audio_inputs:
        cmd += ["-i", str(a)]

    amix = f"[1:a][2:a]amix=inputs={len(audio_inputs)}:duration=first[a];"

    filtros = []
    if bg_png is not None:
        filtros.append(f"scale={WORK_W}:{WORK_H}")
        if sendcmd_path is not None:
            filtros.append(f"sendcmd=f='{_escape(sendcmd_path)}'")
        filtros.append(f"crop={WORK_W}:{WORK_H}")
        # O scale DEPOIS do crop e o que fixa a resolucao de saida. Sem ele o
        # comando do sendcmd nao produz efeito visivel — verificado no ffmpeg 8.1.
        filtros.append(f"scale={OUT_W}:{OUT_H}")
    filtros.append("format=yuv420p")
    filtros.append(f"subtitles='{_escape(ass_path)}'")

    chain = "[0:v]" + ",".join(filtros) + "[v]"

    cmd += [
        "-filter_complex", amix + chain,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        str(out_mp4),
    ]
    return cmd
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_render_cmd.py -v`
Expected: PASS, 5 testes.

- [ ] **Step 5: Controle negativo**

Em `build_render_cmd`, mover a linha `filtros.append(f"scale={OUT_W}:{OUT_H}")` para **antes** do `crop`.
Expected: **FAIL** em `test_scale_vem_depois_do_crop`. Desfazer.

- [ ] **Step 6: Ligar no `09_video_rendering.py`**

Substituir as linhas 516–551 (do comentário `# ── Renderiza Vídeo Final ──` até o `_progress(100, "Video Rendering concluído.")`) por:

```python
    # ── Renderiza Vídeo Final ────────────────────────────────────────────────
    _progress(90, "Renderizando vídeo final (FFmpeg)...")

    import subprocess
    import tempfile

    from karaoke.bounce import build_sendcmd, onsets_from_wav
    from karaoke.render_cmd import WORK_H, WORK_W, build_render_cmd

    out_mp4 = kpaths.output_video(job_id)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    instrumental = (kpaths.separation_dir(job_id) / "htdemucs"
                    / kpaths.input_job_dir(job_id).name / "no_vocals.wav")
    vocals = kpaths.vocals_listen(job_id)

    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(instrumental)],
        capture_output=True, text=True, timeout=30).stdout.strip())

    bg_png = kpaths.background_png(job_id)
    bg_png = bg_png if bg_png.exists() else None

    sendcmd_path = None
    if bg_png is not None:
        try:
            onsets = onsets_from_wav(instrumental)
            sendcmd_path = Path(tempfile.mkstemp(suffix=".txt", prefix="bounce_")[1])
            sendcmd_path.write_text(
                build_sendcmd(onsets, WORK_W, WORK_H), encoding="utf-8")
            print(f"  Bounce: {len(onsets)} onsets -> {sendcmd_path.name}")
        except Exception as e:
            # Sem bounce o fundo fica parado; ainda e melhor que preto chapado.
            print(f"  AVISO: bounce desativado ({type(e).__name__}: {e})")
            sendcmd_path = None

    print(f"  Fundo: {'ilustracao' if bg_png else 'chapado #08090f'}")
    cmd_video = build_render_cmd(bg_png, [instrumental, vocals],
                                 out_ass, out_mp4, duration, sendcmd_path)

    try:
        subprocess.run(cmd_video, check=True, capture_output=True)
        print(f"OK Vídeo final gerado: {out_mp4.name}")
    except subprocess.CalledProcessError as e:
        print(f"ERRO ao renderizar vídeo: {e.stderr.decode(errors='replace')[-2000:]}")
        sys.exit(1)
    finally:
        if sendcmd_path is not None:
            sendcmd_path.unlink(missing_ok=True)

    _progress(100, "Video Rendering concluído.")
```

Conferir que `from pathlib import Path` já está no topo do arquivo; se não estiver, acrescentar.

- [ ] **Step 7: Commit**

```bash
git add karaoke/render_cmd.py scripts/09_video_rendering.py tests/test_render_cmd.py
git commit -m "fix: repara o render do Step 09 e pluga a ilustracao de fundo"
```

---

### Task 6: Registrar o estágio, apagar o órfão e rodar ponta a ponta

**Files:**
- Modify: `run_pipeline.py:119-123`
- Delete: `scripts/08_render_video.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: tudo das tarefas 1–5.
- Produces: nada — é a amarração.

- [ ] **Step 1: Registrar o 08b antes do render**

Ler primeiro `run_pipeline.py:55-131` — o dicionário de estágio pode ter campos além de `name`/`cmd`, e a entrada nova tem de copiar o formato das vizinhas. Entre o estágio `08_onset_dtw.py` (linha 119) e o `09_video_rendering.py` (linha 123), acrescentar:

```python
        {
            "name": "Background Illustration",
            "cmd": [python, _p("scripts", "08b_background_image.py"), "--job-id", job_id]
        },
```

- [ ] **Step 2: Apagar o órfão**

```bash
git rm scripts/08_render_video.py
```

Run: `grep -rn "08_render_video" --include=*.py --include=*.ps1 --include=*.js . | grep -v __pycache__`
Expected: nenhum resultado. Se aparecer algum, repontar antes de seguir.

- [ ] **Step 3: Suíte inteira**

Run: `python -m pytest tests/ -v --ignore=tests/integration`
Expected: PASS. Anotar o número **com denominador** (ex.: "48 passed, 2 skipped"). Se algo que já estava vermelho antes continuar vermelho, dizer isso explicitamente em vez de deixar passar por novo.

- [ ] **Step 4: Verificar a amarração sem disparar o pipeline inteiro**

O plano original mandava rodar um job real aqui. Medido antes de despachar: `work/jobs`
está **vazio** — nenhum job jamais completou neste repositório — e não há
`config/comfy_workflow.json`. Um job real do zero significa Demucs, MFA, WhisperX e
Gemini numa máquina **sem CUDA**, consumindo cota de API, por horas. Isso não é passo
de subagente; é execução que o dono da máquina inicia sabendo o custo.

O que esta tarefa verifica, e que é verificável agora:

```bash
python -c "import run_pipeline, inspect, re; src=inspect.getsource(run_pipeline); \
nomes=re.findall(r'\"scripts\", \"([0-9a-zA-Z_]+\.py)\"', src); \
print(len(nomes), 'estagios'); print(nomes.index('08b_background_image.py'), \
'<', nomes.index('09_video_rendering.py'))"
```

Conferir: o `08b` aparece na lista, e o índice dele é **menor** que o do
`09_video_rendering.py` — o fundo precisa existir antes do render.

Rodar também o `08b` isolado contra um job inexistente e confirmar exit 0 com aviso
(o fallback), que é o comportamento que não pode regredir.

- [ ] **Step 4b: Receita entregue ao usuário, não executada aqui**

Documentar no README, como pré-requisitos explícitos do job real:
1. ComfyUI Desktop aberto, com `config/comfy_workflow.json` exportado em formato API;
2. Ollama de pé (`llama3.2:3b` puxado);
3. `GEMINI_API_KEY` no ambiente;
4. entrada em `input/jobs/{id}/` com `song.mp3` e `lyrics.txt` — ou `input/test_1min/`
   para um snippet de 1 minuto, que é o caminho barato para a primeira validação.

E o que conferir quando rodar: `08_background/background.png` existe e **não tem texto
na imagem**; o log do Step 09 diz `Fundo: ilustracao` e `Bounce: N onsets` com **N > 0**;
o MP4 sai; e, abrindo, a letra está legível sobre o fundo e o fundo pulsa na batida.

O tempo do Step 08b fica como `~Xs` no README até alguém medir. A playbook da AMD alega
<30 s — é alegação de terceiro sobre outro hardware, não medição desta máquina, e o
README deve dizer isso enquanto o número real não existir.

- [ ] **Step 5: Controle negativo ponta a ponta**

```bash
mv work/jobs/{id}/08_background/background.png /tmp/bg_guardado.png
python scripts/09_video_rendering.py --job-id {id}
```
Expected: log diz `Fundo: chapado #08090f`, exit 0, MP4 sai com fundo escuro e legenda normal. Restaurar o PNG depois.

Segundo controle: fechar o ComfyUI e rodar `python scripts/08b_background_image.py --job-id um_job_novo`.
Expected: `AVISO: fundo nao gerado (URLError: ...)` e **exit 0**. O estágio não pode derrubar o pipeline.

- [ ] **Step 6: Documentar**

No `README.md`, na lista "Estágios do Pipeline", acrescentar entre o 8 e o 9:

```markdown
9.  **Background Illustration**: ilustração de fundo gerada localmente a partir
    da letra (Ollama `llama3.2:3b` → ComfyUI `z_image_turbo`). Requer os dois
    serviços de pé; sem eles o vídeo sai com fundo chapado. Tempo medido: ~Xs.
```

Renumerar os itens seguintes. Substituir `~Xs` pelo tempo medido no Step 4.

- [ ] **Step 7: Commit**

```bash
git add run_pipeline.py README.md
git commit -m "feat: registra o estagio de fundo e remove o renderizador orfao"
```

---

### Task 5B: Reparar os 3 estágios vivos que o `run_pipeline` executa

Tarefa acrescentada depois que a medição mostrou que o defeito da Task 1 não era
isolado. Sem ela, a Task 6 Step 4 não tem como rodar: o `run_pipeline` morre no
terceiro estágio, muito antes do vídeo. Escopo aprovado pelo usuário.

**Files:**
- Modify: `karaoke/paths.py`
- Modify: `scripts/07_gemini_alignment.py:463`, `scripts/03c_gemini_transcribe.py:463`
- Test: `tests/test_paths_contract.py`

**Interfaces:**
- Consumes: o teste de contrato da Task 1.
- Produces: `kpaths.corpus_dir(job_id) -> Path`, `kpaths.char_timing_json(job_id) -> Path`.

**Medido antes de escrever esta tarefa** — 17 acessores `kpaths` ausentes em 11 de
28 arquivos que citam `kpaths`. Destes, só 3 estão em estágios que o
`run_pipeline.py` de fato executa, e são o escopo desta tarefa:

| estágio vivo | ausente |
|---|---|
| `03_prepare_corpus.py:129` | `corpus_dir` |
| `06_alignment_rescue.py:181,183` | `char_timing_json`, `corpus_dir` |
| `07_gemini_alignment.py:463` | `lyrics_txt` |

Os outros 14 ficam fora: estão em scripts que o `run_pipeline` não chama.

- [ ] **Step 1: Alargar o teste de contrato para pegar isto**

`tests/test_paths_contract.py` hoje examina 6 scripts escolhidos a dedo. Trocar
essa lista pelos scripts que o `run_pipeline.py` realmente executa, derivados do
próprio `run_pipeline.py` em vez de escritos à mão — lista escrita à mão foi
exatamente como estes três passaram.

```python
def _scripts_vivos():
    """Scripts que run_pipeline.py de fato executa, lidos dele mesmo."""
    src = io.open(ROOT / "run_pipeline.py", encoding="utf-8").read()
    nomes = sorted(set(re.findall(r'"scripts",\s*"([0-9a-zA-Z_]+\.py)"', src)))
    assert nomes, "nenhum script encontrado em run_pipeline.py — teste inutil"
    return [f"scripts/{n}" for n in nomes]
```

Usar isso como fonte de `SCRIPTS`, mantendo o `pytest.skip` para arquivo que
ainda não exista. O `assert nomes` é a cardinalidade: lista vazia aqui seria
verde universal.

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_paths_contract.py -v`
Expected: FAIL, acusando `corpus_dir`, `char_timing_json` e `lyrics_txt` com o
denominador de quantos acessores foram examinados em cada script.

- [ ] **Step 3: Confirmar onde o corpus vive de verdade**

`corpus_dir` é usado como `corpus_dir(job_id) / "song.lab"`, e `mfa_corpus_dir`
já existe apontando para `04_mfa_corpus`. Antes de criar alias, confirmar que
quem **grava** (`03_prepare_corpus.py`) e quem **lê** (`04_mfa_alignment.py`,
que aponta o MFA para o corpus) usam o mesmo diretório. Se divergirem, o alias
está errado e o acessor deve seguir o que o MFA realmente lê.

Run: `grep -nE "corpus|\.lab|mfa_corpus_dir" scripts/03_prepare_corpus.py scripts/04_mfa_alignment.py`

- [ ] **Step 4: Repontar `lyrics_txt`**

`kpaths.lyrics_path` já existe e é a mesma letra. Trocar nos dois call sites
(`07_gemini_alignment.py:463` e `03c_gemini_transcribe.py:463`) e **não** criar
um acessor `lyrics_txt`. Um nome por conceito — mesma decisão da Task 1.

- [ ] **Step 5: Acrescentar os dois acessores**

```python
def corpus_dir(job_id: str) -> Path:
    """Corpus .lab que o MFA consome. Alias de mfa_corpus_dir."""
    return mfa_corpus_dir(job_id)

def char_timing_json(job_id: str) -> Path:
    """Timing por caractere do CTC. Gravado por 03_forced_align.py:138."""
    return alignment_dir(job_id) / "char_timing.json"
```

Se o Step 3 mostrar que o corpus não é `04_mfa_corpus`, ajustar e anotar no commit.

- [ ] **Step 6: Rodar e ver passar**

Run: `python -m pytest tests/test_paths_contract.py -v`
Expected: PASS, **0 skipped**, e o teste agora cobre todos os estágios vivos.

- [ ] **Step 7: Controle negativo**

Renomear `char_timing_json` para `char_timing_json_x` e rodar de novo.
Expected: **FAIL** nomeando o acessor e o total examinado. Desfazer.

- [ ] **Step 8: Commit**

```bash
git add karaoke/paths.py scripts/07_gemini_alignment.py scripts/03c_gemini_transcribe.py tests/test_paths_contract.py
git commit -m "fix: repara os acessores kpaths dos estagios vivos do pipeline"
```

---

## Self-review

Cobertura do spec, requisito por requisito:

| requisito do spec | tarefa |
|---|---|
| Reparar acessores ausentes (6) | Task 1 |
| `background_png()` | Task 1 |
| Brief local via Ollama | Task 3 |
| Imagem local via ComfyUI + Z-Image-Turbo | Task 4 |
| Regras fixas de prompt (sem texto, centro escuro, 16:9) | Task 3 (`IMAGE_RULES`) + teste |
| Letra crua não vai ao gerador de imagem | Task 3, `test_letra_crua_nao_vaza_para_o_prompt_de_imagem` |
| Cache | Task 4 Step 6 |
| Fallback para `#08090f` | Task 5 + Task 6 Step 5 |
| `bounce.txt` dos onsets do instrumental | Task 2 + Task 5 Step 6 |
| Um filtro só (sem `zoompan`) | Task 5 — `build_render_cmd` não usa zoompan |
| Cardinalidade > 0 nos onsets | Task 2, `test_lista_vazia_e_erro_nao_arquivo_vazio` |
| Controles negativos | Tasks 1, 2, 5 (steps próprios) + Task 6 Step 5 |
| Deletar `08_render_video.py` | Task 6 Step 2 |
| Porta do ComfyUI a confirmar | Task 4 Step 1 |
| Sintaxe do `sendcmd` | resolvida antes do plano; virou Global Constraint |

Nomes conferidos entre tarefas: `build_sendcmd`/`onsets_from_wav` (Task 2) são exatamente os importados na Task 5 Step 6. `build_brief`/`image_prompt`/`generate_image`/`_inject_prompt` (Tasks 3–4) batem com o uso em `08b`. `build_render_cmd`, `WORK_W`, `WORK_H` (Task 5) batem entre `karaoke/render_cmd.py` e o call site. `_post_json` é definido na Task 3 e reusado na Task 4.

Um desvio consciente em relação ao spec: o spec falava em reparar o bloco de render dentro de `09_video_rendering.py`, e o plano extrai a montagem do comando para `karaoke/render_cmd.py`. Motivo: sem isso não há como testar o comando sem rodar o encoder. Segue o padrão de `karaoke/ass_builder.py`, que já separa lógica testável de script.
