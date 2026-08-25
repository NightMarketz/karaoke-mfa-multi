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
