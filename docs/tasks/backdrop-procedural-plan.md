# Backdrop Procedural (fatia A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O s07 deixa de renderizar letra sobre preto — o fundo é gerado em lavfi e muda de cor por seção, sem asset externo e sem estágio novo.

**Architecture:** O s06 (que já lê `analysis.json` e escreve `output.ass`) passa a escrever também `backdrop.cmd`, um arquivo de comandos do `sendcmd`. O s07 troca o canvas `color=c=black` por `gradients`, e injeta `sendcmd=f=backdrop.cmd,huesaturation` antes do `ass=`. As cores base do gradiente são fixas (E005: `c0`–`c7` não são comandáveis); toda a variação por seção vem do `huesaturation` a jusante.

**Tech Stack:** Python 3 (stdlib + `pysubs2`, já presentes), ffmpeg 8.1 com libass/AMF, pytest.

**Spec:** [backdrop-procedural.md](backdrop-procedural.md) — os IDs `E001`–`E010` abaixo referenciam a tabela de evidência de lá.

## Global Constraints

- Nenhum estágio novo. `s01–s08` e seus nomes de artefato são contrato.
- `analysis.json` é **lido**, nunca escrito, por esta fatia. Contrato inalterado.
- A paleta é indexada pelas **5 cores** de `STYLE_DEFAULTS`, nunca pelos 9 `style` (E003/E004).
- `supported_style_keys()` / `STYLE_DEFAULTS` em `scripts/karaoke_styles/library.py` continuam sendo fonte única do eixo de estilo.
- Precedência de config: CLI > env > `pipeline.toml` > default.
- Faixas dos parâmetros, verbatim do filtro: `hue` −180..180, `saturation` −1..1, `intensity` −1..1.
- Nada de `analysis.json` é interpolado cru numa string de filtergraph. O rótulo só **indexa** a paleta.
- Backdrop é cosmético: qualquer falha dele cai para canvas preto e o render **continua**.
- Verificação só por `pytest`. `unittest` reporta 0 testes em suítes deste repo (E010) — todo número vem com denominador.
- Classes de teste **devem** herdar `unittest.TestCase` (convenção do repo, e o que as torna visíveis nos dois runners).

---

### Task 1: Paleta de backdrop indexada por cor

**Files:**
- Create: `scripts/karaoke_styles/backdrop.py`
- Test: `tests/test_backdrop_contract.py`

**Interfaces:**
- Consumes: `STYLE_DEFAULTS` de `scripts/karaoke_styles/library.py` (9 chaves de style, cada uma com `{"color": str, "effect": str}`).
- Produces: `BACKDROP_PALETTE: dict[str, dict[str, float]]` e `backdrop_for_color(color: str) -> dict[str, float]`. A dict retornada tem exatamente as chaves `{"hue", "saturation", "intensity"}` com valores `float`.

- [ ] **Step 1: Write the failing test**

```python
"""Contract tests for the procedural backdrop (fatia A)."""

import unittest

from scripts.karaoke_styles.backdrop import BACKDROP_PALETTE, backdrop_for_color
from scripts.karaoke_styles.library import STYLE_DEFAULTS

_RANGES = {"hue": (-180.0, 180.0), "saturation": (-1.0, 1.0), "intensity": (-1.0, 1.0)}


class PaletteCoverageTests(unittest.TestCase):
    def test_every_colour_used_by_style_defaults_has_a_palette_entry(self):
        used = {v["color"] for v in STYLE_DEFAULTS.values()}
        self.assertEqual(5, len(used), f"eixo de cor mudou: {sorted(used)}")
        self.assertEqual(used, set(BACKDROP_PALETTE), "paleta divergiu de STYLE_DEFAULTS")

    def test_palette_has_no_orphan_entries(self):
        used = {v["color"] for v in STYLE_DEFAULTS.values()}
        self.assertEqual(set(), set(BACKDROP_PALETTE) - used)

    def test_every_style_resolves_to_a_backdrop(self):
        resolved = [backdrop_for_color(v["color"]) for v in STYLE_DEFAULTS.values()]
        self.assertEqual(len(STYLE_DEFAULTS), len(resolved))
        self.assertEqual(9, len(resolved), "denominador: 9 styles")

    def test_all_values_are_inside_the_filter_ranges(self):
        checked = 0
        for colour, params in BACKDROP_PALETTE.items():
            self.assertEqual({"hue", "saturation", "intensity"}, set(params), colour)
            for param, value in params.items():
                low, high = _RANGES[param]
                self.assertIsInstance(value, float, f"{colour}.{param}")
                self.assertGreaterEqual(value, low, f"{colour}.{param}")
                self.assertLessEqual(value, high, f"{colour}.{param}")
                checked += 1
        self.assertEqual(15, checked, "denominador: 5 cores x 3 params")

    def test_unknown_colour_falls_back_to_neutral(self):
        self.assertEqual(
            {"hue": 0.0, "saturation": 0.0, "intensity": 0.0},
            backdrop_for_color("nao-existe"),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backdrop_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.karaoke_styles.backdrop'`

- [ ] **Step 3: Write minimal implementation**

```python
"""
backdrop.py — Paleta e emissão de comandos do fundo procedural (fatia A).

A paleta é indexada pelos valores de `color` de STYLE_DEFAULTS (5), não pelos
style keys (9). Um rótulo de seção novo herda um fundo de graça, e isto não
vira mais uma superfície seção→X (ver docs/tasks/section-style-map-duplication.md).

Os valores são deltas aplicados pelo filtro `huesaturation` do ffmpeg sobre um
gradiente de cores fixas — `gradients` não aceita comando em c0-c7.
"""

from __future__ import annotations

NEUTRAL: dict[str, float] = {"hue": 0.0, "saturation": 0.0, "intensity": 0.0}

BACKDROP_PALETTE: dict[str, dict[str, float]] = {
    "soft":    {"hue": -20.0, "saturation": -0.35, "intensity": -0.10},
    "default": {"hue":   0.0, "saturation":  0.00, "intensity":  0.00},
    "cool":    {"hue":  40.0, "saturation":  0.10, "intensity": -0.05},
    "warm":    {"hue": -55.0, "saturation":  0.20, "intensity":  0.05},
    "intense": {"hue": -75.0, "saturation":  0.45, "intensity":  0.15},
}


def backdrop_for_color(color: str) -> dict[str, float]:
    """Deltas de huesaturation para um token de cor. Desconhecido -> neutro."""
    return dict(BACKDROP_PALETTE.get(color, NEUTRAL))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backdrop_contract.py -q`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/karaoke_styles/backdrop.py tests/test_backdrop_contract.py
git commit -m "feat(backdrop): paleta indexada pelas 5 cores de STYLE_DEFAULTS"
```

---

### Task 2: Emissor de comandos com whitelist

**Files:**
- Modify: `scripts/karaoke_styles/backdrop.py`
- Test: `tests/test_backdrop_contract.py`

**Interfaces:**
- Consumes: `BACKDROP_PALETTE`, `backdrop_for_color()` da Task 1.
- Produces: `emit_backdrop_commands(lines: list[dict]) -> str`. Recebe a lista `analysis["lines"]` (cada item com `"color": str` e `"start": float`) e devolve o conteúdo do `backdrop.cmd`. Emite um bloco de 3 comandos na cor inicial (t=0) e um bloco a cada **troca de cor** entre linhas consecutivas. Levanta `ValueError` em parâmetro fora da whitelist, valor fora de faixa ou timestamp não-monotônico.

- [ ] **Step 1: Write the failing test**

Acrescentar ao fim de `tests/test_backdrop_contract.py`:

```python
from scripts.karaoke_styles.backdrop import emit_backdrop_commands


def _line(color, start):
    return {"color": color, "start": start, "text": "x", "end": start + 1.0}


class EmitCommandTests(unittest.TestCase):
    def test_emits_one_block_per_colour_change_plus_initial(self):
        lines = [_line("soft", 0.5), _line("soft", 2.0),
                 _line("intense", 4.0), _line("intense", 6.0),
                 _line("warm", 8.0)]
        out = emit_backdrop_commands(lines)
        blocks = [l for l in out.splitlines() if l.strip()]
        # 3 cores observadas (soft inicial, ->intense, ->warm) x 3 params
        self.assertEqual(9, len(blocks), f"esperado 3 blocos x 3 params, veio:\n{out}")

    def test_timestamps_are_monotonic_and_start_at_zero(self):
        lines = [_line("soft", 5.0), _line("warm", 9.0)]
        times = [float(l.split()[0])
                 for l in emit_backdrop_commands(lines).splitlines() if l.strip()]
        self.assertEqual(6, len(times), "denominador: 2 blocos x 3 params")
        self.assertEqual(0.0, times[0], "primeiro bloco tem de ancorar em t=0")
        self.assertEqual(sorted(times), times)

    def test_every_command_targets_only_the_whitelisted_filter_and_params(self):
        lines = [_line(c, i * 2.0) for i, c in enumerate(BACKDROP_PALETTE)]
        emitted = [l for l in emit_backdrop_commands(lines).splitlines() if l.strip()]
        self.assertEqual(15, len(emitted), "denominador: 5 cores x 3 params")
        for line in emitted:
            _t, target, param, _value = line.rstrip(";").split()
            self.assertEqual("huesaturation", target)
            self.assertIn(param, {"hue", "saturation", "intensity"})

    def test_hostile_section_label_cannot_escape_into_the_filtergraph(self):
        # Rotulo hostil vindo do caminho Whisper/LLM. So indexa a paleta.
        lines = [_line("chorus; drawtext=text=pwn", 0.0)]
        out = emit_backdrop_commands(lines)
        self.assertNotIn("drawtext", out)
        self.assertNotIn("pwn", out)
        emitted = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(3, len(emitted), "cai no neutro, ainda 3 params")

    def test_empty_lines_produce_empty_output(self):
        self.assertEqual("", emit_backdrop_commands([]))

    def test_out_of_range_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            emit_backdrop_commands([_line("soft", 0.0), _line("warm", -5.0)])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backdrop_contract.py -q`
Expected: FAIL — `ImportError: cannot import name 'emit_backdrop_commands'`

- [ ] **Step 3: Write minimal implementation**

Acrescentar a `scripts/karaoke_styles/backdrop.py`:

```python
_FILTER = "huesaturation"
_ALLOWED: dict[str, tuple[float, float]] = {
    "hue": (-180.0, 180.0),
    "saturation": (-1.0, 1.0),
    "intensity": (-1.0, 1.0),
}


def _command(t: float, param: str, value: float, last_t: float) -> str:
    """Uma linha de sendcmd, validada. Fronteira de confianca da fatia A."""
    if param not in _ALLOWED:
        raise ValueError(f"parametro fora da whitelist: {param!r}")
    low, high = _ALLOWED[param]
    if not isinstance(value, (int, float)) or not (low <= float(value) <= high):
        raise ValueError(f"{param}={value!r} fora da faixa [{low}, {high}]")
    if t < 0.0 or t < last_t:
        raise ValueError(f"timestamp nao-monotonico: {t} apos {last_t}")
    return f"{t:.3f} {_FILTER} {param} {float(value):.4f};"


def emit_backdrop_commands(lines: list[dict]) -> str:
    """analysis["lines"] -> conteudo de backdrop.cmd. Um bloco por troca de cor."""
    out: list[str] = []
    previous_colour: object = object()
    last_t = 0.0
    for index, line in enumerate(lines):
        colour = line.get("color")
        if colour == previous_colour:
            continue
        # O primeiro bloco ancora em 0 para o fundo ja nascer certo.
        t = 0.0 if index == 0 else float(line.get("start", 0.0))
        for param, value in backdrop_for_color(colour).items():
            out.append(_command(t, param, value, last_t))
        last_t = t
        previous_colour = colour
    return "\n".join(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backdrop_contract.py -q`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/karaoke_styles/backdrop.py tests/test_backdrop_contract.py
git commit -m "feat(backdrop): emissor de sendcmd com whitelist na fronteira de confianca"
```

---

### Task 3: s06 escreve backdrop.cmd e o registra no manifest

**Files:**
- Modify: `scripts/s06_generate_ass.py` (import junto aos demais de `karaoke_styles`; bloco de escrita em `:1153-1195`)
- Test: `tests/test_s06_backdrop_output.py`

**Interfaces:**
- Consumes: `emit_backdrop_commands()` da Task 2.
- Produces: `_write_backdrop(job_dir: Path, lines: list[dict]) -> Path | None`, o arquivo `jobs/{id}/backdrop.cmd` (UTF-8 **sem** BOM — o `sendcmd` não tolera BOM, ao contrário do `.ass`), e a entrada `"backdrop.cmd"` em `outputs` do `output.ass.manifest.json`.

- [ ] **Step 1: Write the failing test**

```python
"""s06 tem de emitir backdrop.cmd ao lado de output.ass."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

pytest.importorskip("pysubs2")

from scripts.s06_generate_ass import _write_backdrop


class WriteBackdropTests(unittest.TestCase):
    def test_writes_file_without_bom(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            path = _write_backdrop(job, [{"color": "soft", "start": 0.0},
                                         {"color": "intense", "start": 4.0}])
            self.assertEqual(job / "backdrop.cmd", path)
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "sendcmd nao tolera BOM")
            self.assertEqual(6, len(raw.decode("utf-8").strip().splitlines()))

    def test_returns_none_and_writes_nothing_when_there_are_no_lines(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            self.assertIsNone(_write_backdrop(job, []))
            self.assertFalse((job / "backdrop.cmd").exists())

    def test_invalid_input_does_not_raise_out_of_the_stage(self):
        # Backdrop e' cosmetico: nunca derruba o s06.
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            bad = [{"color": "soft", "start": 0.0}, {"color": "warm", "start": -5.0}]
            self.assertIsNone(_write_backdrop(job, bad))
            self.assertFalse((job / "backdrop.cmd").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_s06_backdrop_output.py -q`
Expected: FAIL — `ImportError: cannot import name '_write_backdrop'`

- [ ] **Step 3: Write minimal implementation**

Adicionar o import junto aos outros de `karaoke_styles` em `scripts/s06_generate_ass.py`:

```python
from scripts.karaoke_styles.backdrop import emit_backdrop_commands
```

Adicionar a função imediatamente acima de `def main()`:

```python
def _write_backdrop(job_dir: Path, lines: list[dict]) -> Path | None:
    """
    Escreve backdrop.cmd a partir das cores de analysis.json.

    Cosmetico: qualquer falha devolve None e o s07 cai para canvas preto.
    Nunca levanta — um fundo ruim nao pode impedir um export.
    """
    try:
        content = emit_backdrop_commands(lines)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.warning("backdrop.cmd nao gerado: %s", exc)
        return None
    if not content:
        return None
    path = job_dir / "backdrop.cmd"
    path.write_text(content + "\n", encoding="utf-8")  # sem BOM
    return path
```

Em `main()`, logo depois de `output_path.write_bytes(...)` (`:1155`) e **antes** de `write_manifest(...)`:

```python
    backdrop_path = _write_backdrop(job_dir, lines)
```

Dentro do dict passado a `write_manifest`, na chave `"outputs"`, ao lado de `"output.ass"`:

```python
                **({"backdrop.cmd": {"path": "backdrop.cmd"}} if backdrop_path else {}),
```

E no `output_paths=` da mesma chamada:

```python
        output_paths={
            "output.ass": output_path,
            **({"backdrop.cmd": backdrop_path} if backdrop_path else {}),
        },
```

Logo após o `_stage06_event(... "stage06.ass_written" ...)`:

```python
    _stage06_event(
        job_dir,
        "stage06.backdrop_written" if backdrop_path else "stage06.backdrop_skipped",
        path=str(backdrop_path) if backdrop_path else "",
        command_count=(
            len(backdrop_path.read_text(encoding="utf-8").strip().splitlines())
            if backdrop_path else 0
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_s06_backdrop_output.py tests/test_s06_style_contracts.py -q`
Expected: PASS — 3 passed no arquivo novo; o suite de estilo do s06 segue verde.

- [ ] **Step 5: Commit**

```bash
git add scripts/s06_generate_ass.py tests/test_s06_backdrop_output.py
git commit -m "feat(s06): emitir backdrop.cmd e registrar no manifest"
```

---

### Task 4: s07 consome o backdrop, com config e fallback

**Files:**
- Modify: `scripts/common/config.py` (campos de `AppConfig` em `:92-103`; construção em `:283-308`)
- Modify: `pipeline.toml` (seção `[generate]`)
- Modify: `scripts/s07_output.py` (`_build_subtitle_filter` em `:87`; canvas em `:624-648`; `vf_filter` em `:646`; argparse em `:406`)
- Test: `tests/test_s07_backdrop.py`

**Interfaces:**
- Consumes: `backdrop.cmd` escrito pela Task 3.
- Produces: `_ffmpeg_path(path: Path) -> str`, `_build_backdrop_source(resolution: str, framerate: str, duration: float, c0: str, c1: str, gtype: str, speed: float) -> str` e `_build_backdrop_filter(cmd_path: Path | None) -> str`. O último devolve `""` quando `cmd_path` é `None`, e a cadeia `sendcmd=f='…',huesaturation` quando não é. Campos novos de `AppConfig`: `generate_backdrop: bool`, `generate_backdrop_c0: str`, `generate_backdrop_c1: str`, `generate_backdrop_type: str`, `generate_backdrop_speed: float`.

- [ ] **Step 1: Write the failing test**

```python
"""s07 tem de montar o canvas procedural quando ha backdrop.cmd."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.s07_output import _build_backdrop_filter, _build_backdrop_source


class BackdropSourceTests(unittest.TestCase):
    def test_source_is_a_gradients_with_fixed_colours(self):
        src = _build_backdrop_source("1920x1080", "30", 12.5,
                                     "0x0a0a18", "0x2a1060", "radial", 0.02)
        self.assertIn("gradients=", src)
        self.assertIn("s=1920x1080", src)
        self.assertIn("c0=0x0a0a18", src)
        self.assertIn("d=12.500", src)
        self.assertNotIn("color=c=black", src)


class BackdropFilterTests(unittest.TestCase):
    def test_no_cmd_file_yields_empty_filter(self):
        self.assertEqual("", _build_backdrop_filter(None))

    def test_cmd_file_yields_sendcmd_then_huesaturation(self):
        with TemporaryDirectory() as tmp:
            cmd = Path(tmp) / "backdrop.cmd"
            cmd.write_text("0.000 huesaturation hue 0.0000;\n", encoding="utf-8")
            out = _build_backdrop_filter(cmd)
            self.assertTrue(out.startswith("sendcmd=f="), out)
            self.assertTrue(out.endswith(",huesaturation"), out)
            self.assertNotIn("\\\\", out, "caminho tem de usar barras normais")

    def test_windows_drive_colon_is_escaped(self):
        out = _build_backdrop_filter(Path("C:/jobs/x/backdrop.cmd"))
        self.assertIn("C\\:/jobs/x/backdrop.cmd", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_s07_backdrop.py -q`
Expected: FAIL — `ImportError: cannot import name '_build_backdrop_filter'`

- [ ] **Step 3: Write minimal implementation**

Em `scripts/common/config.py`, adicionar aos campos de `AppConfig` (junto de `generate_fade_out_ms`, `:103`):

```python
    generate_backdrop: bool
    generate_backdrop_c0: str
    generate_backdrop_c1: str
    generate_backdrop_type: str
    generate_backdrop_speed: float
```

Adicionar os defaults junto às demais constantes `DEFAULT_GENERATE_*`:

```python
DEFAULT_GENERATE_BACKDROP = True
DEFAULT_GENERATE_BACKDROP_C0 = "0x0a0a18"
DEFAULT_GENERATE_BACKDROP_C1 = "0x2a1060"
DEFAULT_GENERATE_BACKDROP_TYPE = "radial"
DEFAULT_GENERATE_BACKDROP_SPEED = 0.02
```

Na construção, logo depois de `generate_fade_out_ms=...` (`:308`):

```python
        generate_backdrop=_bool_value(
            _env_or_value("KARAOKE_GENERATE_BACKDROP", generate.get("backdrop"), None),
            DEFAULT_GENERATE_BACKDROP,
        ),
        generate_backdrop_c0=str(
            _env_or_value("KARAOKE_GENERATE_BACKDROP_C0",
                          generate.get("backdrop_c0"), DEFAULT_GENERATE_BACKDROP_C0)
        ),
        generate_backdrop_c1=str(
            _env_or_value("KARAOKE_GENERATE_BACKDROP_C1",
                          generate.get("backdrop_c1"), DEFAULT_GENERATE_BACKDROP_C1)
        ),
        generate_backdrop_type=str(
            _env_or_value("KARAOKE_GENERATE_BACKDROP_TYPE",
                          generate.get("backdrop_type"), DEFAULT_GENERATE_BACKDROP_TYPE)
        ),
        generate_backdrop_speed=_float_env_or_value(
            "KARAOKE_GENERATE_BACKDROP_SPEED",
            generate.get("backdrop_speed"), DEFAULT_GENERATE_BACKDROP_SPEED,
        ),
```

Em `pipeline.toml`, na seção `[generate]`:

```toml
# Fundo procedural (fatia A). c0/c1 sao fixos: gradients nao aceita comando
# nesses parametros — a variacao por secao vem do huesaturation a jusante.
backdrop       = true
backdrop_c0    = "0x0a0a18"
backdrop_c1    = "0x2a1060"
backdrop_type  = "radial"   # linear | radial | circular | spiral | square
backdrop_speed = 0.02
```

Em `scripts/s07_output.py`, logo abaixo de `_build_subtitle_filter` (`:95`):

```python
def _ffmpeg_path(path: Path) -> str:
    """Caminho seguro para dentro de um filtergraph (Windows: / e : escapado)."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def _build_backdrop_source(
    resolution: str, framerate: str, duration: float,
    c0: str, c1: str, gtype: str, speed: float,
) -> str:
    """Fonte lavfi do fundo procedural. c0/c1 fixos — nao sao comandaveis."""
    return (
        f"gradients=s={resolution}:r={framerate}:d={duration:.3f}"
        f":c0={c0}:c1={c1}:type={gtype}:speed={speed}"
    )


def _build_backdrop_filter(cmd_path: Path | None) -> str:
    """sendcmd + huesaturation, ou vazio quando nao ha backdrop.cmd."""
    if cmd_path is None:
        return ""
    return f"sendcmd=f='{_ffmpeg_path(cmd_path)}',huesaturation"
```

Refatorar `_build_subtitle_filter` para usar o helper novo (comportamento idêntico):

```python
def _build_subtitle_filter(ass_path: Path) -> str:
    """
    Build the ass= filter string for filter_complex.
    On Windows, the path must be escaped for the filtergraph (forward slashes + escaped colons)
    and quoted to prevent being misinterpreted as filter options.
    """
    return f"ass=filename='{_ffmpeg_path(ass_path)}'"
```

Adicionar a flag no argparse, junto de `--no-subtitles` (`:406`):

```python
    parser.add_argument(
        "--no-backdrop", action="store_true",
        help="Force the black canvas, ignoring backdrop.cmd.",
    )
```

Substituir o bloco do canvas (`:624-648`) por:

```python
    backdrop_cmd: Path | None = None
    backdrop_reason = ""
    if not app_config.generate_backdrop:
        backdrop_reason = "disabled_by_config"
    elif args.no_backdrop:
        backdrop_reason = "disabled_by_flag"
    else:
        candidate = job_dir / "backdrop.cmd"
        if not candidate.exists():
            backdrop_reason = "missing"
        elif candidate.stat().st_size == 0:
            backdrop_reason = "empty"
        else:
            backdrop_cmd = candidate

    if backdrop_cmd is None:
        # Cosmetico: registra o motivo e segue para o canvas preto.
        write_event(
            job_dir,
            "stage07.backdrop_skipped",
            STAGE,
            message=f"Procedural backdrop skipped ({backdrop_reason})",
            details={"reason": backdrop_reason},
        )

    if backdrop_cmd is not None:
        canvas_source = _build_backdrop_source(
            args.resolution, args.framerate, canvas_duration,
            app_config.generate_backdrop_c0, app_config.generate_backdrop_c1,
            app_config.generate_backdrop_type, app_config.generate_backdrop_speed,
        )
        background = "gradients"
    else:
        canvas_source = (
            f"color=c=black:s={args.resolution}:r={args.framerate}:d={canvas_duration:.3f}"
        )
        background = "black"

    cmd += ["-f", "lavfi", "-i", canvas_source]
    write_event(
        job_dir,
        "stage07.canvas_selected",
        STAGE,
        message="Synthetic background canvas selected",
        details={
            "background": background,
            "backdrop_sha256": file_sha256(backdrop_cmd) if backdrop_cmd else "",
            "resolution": args.resolution,
            "framerate": args.framerate,
            "duration_seconds": canvas_duration,
            "source": "instrumental_duration_plus_buffer"
            if canvas_duration != 3600.0
            else "fallback",
        },
    )
```

Substituir a montagem do `vf_filter` (`:646`) por:

```python
    backdrop_filter = _build_backdrop_filter(backdrop_cmd)
    subtitle_filter = _build_subtitle_filter(ass_path) if ass_path else ""
    vf_chain = [f for f in (backdrop_filter, subtitle_filter) if f]
    vf_filter = ",".join(vf_chain) if vf_chain else "null"
```

Se `file_sha256` ainda não estiver importado no s07, adicioná-lo ao import de `scripts.common.provenance`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_s07_backdrop.py tests/test_app_config.py tests/test_s07_observability.py -q`
Expected: PASS — 4 passed no arquivo novo (1 em `BackdropSourceTests` + 3 em `BackdropFilterTests`); config e observabilidade seguem verdes.

- [ ] **Step 5: Commit**

```bash
git add scripts/s07_output.py scripts/common/config.py pipeline.toml tests/test_s07_backdrop.py
git commit -m "feat(s07): canvas procedural com sendcmd, config e fallback para preto"
```

---

### Task 5: Cerca ITU sobre o MP4 renderizado

**Files:**
- Create: `tests/test_backdrop_itu.py`

**Interfaces:**
- Consumes: só o binário `ffmpeg` — o teste não importa código de estágio.
- Produces: nada consumido por outras tasks. É o portão final.

Converte por ITU-R BT.1702-3 Annex 2: 10-bit `V = (D−64)/876`, EOTF BT.1886, SDR peak white 200 cd/m². Limite da Guideline 1: par de mudanças opostas `< 20 cd/m²`.

- [ ] **Step 1: Write the failing test**

```python
"""Cerca de fotossensibilidade (ITU-R BT.1702-3) sobre o video renderizado.

Mede luminancia por frame na faixa da letra e exige variacao < 20 cd/m2.
Traz o proprio controle negativo: um estrobo deliberado tem de ficar vermelho,
senao a cerca nao discrimina e o verde nao vale nada.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

if shutil.which("ffmpeg") is None:
    pytest.skip("ffmpeg nao encontrado no PATH", allow_module_level=True)

THRESHOLD_CDM2 = 20.0


def _luma_series(src: Path, crop: str | None = None) -> list[float]:
    vf = (f"{crop}," if crop else "") + "signalstats,metadata=print:key=lavfi.signalstats.YAVG"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-vf", vf, "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    return [float(m) for m in re.findall(r"YAVG=([0-9.]+)", proc.stderr)]


def _cdm2(code8: float) -> float:
    """8-bit YAVG -> cd/m2. BT.1702-3 Annex 2 + EOTF BT.1886, peak white 200."""
    v = (code8 * 4 - 64) / 876.0
    return 200.0 * max(v, 0.0) ** 2.4


def _delta(series: list[float]) -> float:
    lums = [_cdm2(x) for x in series]
    return max(lums) - min(lums)


def _render(dst: Path, vsrc: str, duration: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", vsrc,
         "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", str(dst)],
        check=True, capture_output=True, timeout=120,
    )
    return dst


class PhotosensitivityFenceTests(unittest.TestCase):
    def test_procedural_backdrop_stays_under_the_flash_threshold(self):
        with TemporaryDirectory() as tmp:
            mp4 = _render(
                Path(tmp) / "backdrop.mp4",
                "gradients=s=320x180:r=30:c0=0x0a0a18:c1=0x2a1060:type=radial:speed=0.02",
            )
            band = _luma_series(mp4, crop="crop=320:34:0:146")  # faixa da letra
            self.assertGreater(len(band), 0, "serie vazia nao e' aprovacao")
            self.assertEqual(60, len(band), "denominador: 2s x 30fps")
            self.assertLess(_delta(band), THRESHOLD_CDM2)

    def test_the_fence_goes_red_on_a_deliberate_strobe(self):
        # Controle negativo. Sem isto, o teste acima e' verde universal.
        with TemporaryDirectory() as tmp:
            mp4 = _render(
                Path(tmp) / "strobe.mp4",
                "nullsrc=s=320x180:r=30,geq=lum='if(lt(mod(T*30,2),1),235,16)':cb=128:cr=128",
            )
            series = _luma_series(mp4)
            self.assertEqual(60, len(series), "denominador: 2s x 30fps")
            self.assertGreaterEqual(
                _delta(series), THRESHOLD_CDM2,
                "a cerca nao detectou um estrobo — ela nao discrimina",
            )
```

- [ ] **Step 2: Run test to verify it fails**

O controle negativo (`test_the_fence_goes_red_on_a_deliberate_strobe`) é o que prova que a
cerca discrimina; ele falha se o limite não morder. Para confirmar que o **teste positivo**
também é load-bearing, baixar `THRESHOLD_CDM2` para `0.0` e rodar:

Run: `pytest tests/test_backdrop_itu.py -q`
Expected: FAIL em `test_procedural_backdrop_stays_under_the_flash_threshold`. Restaurar para `20.0` em seguida.

- [ ] **Step 3: Write minimal implementation**

Nenhum código de produção. O comportamento já foi entregue nas Tasks 1–4; esta task é a cerca.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backdrop_itu.py -q`
Expected: PASS — 2 passed (alvo abaixo do limite, estrobo acima).

- [ ] **Step 5: Commit**

```bash
git add tests/test_backdrop_itu.py
git commit -m "test(backdrop): cerca ITU-R BT.1702-3 com controle negativo"
```

---

## Verificação final

```bash
pytest tests/test_backdrop_contract.py tests/test_backdrop_itu.py tests/test_s07_backdrop.py tests/test_s06_backdrop_output.py -q
```

```bash
pytest tests/test_app_config.py tests/test_s07_observability.py tests/test_s06_style_contracts.py tests/test_karaoke_style_library.py -q
```

Reportar contagens com denominador. Nunca `unittest` (E010).
