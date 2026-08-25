"""Contrato: todo kpaths.X citado nos scripts de render tem de existir."""
import io
import re
from pathlib import Path

import pytest

import karaoke.paths as kpaths

ROOT = Path(__file__).resolve().parent.parent

# Lista escrita a mao (os 6 scripts do fix round 1) deixou passar 3 acessores
# ausentes em estagios que o run_pipeline.py de fato executa (Task 5B). Em vez
# de mais uma lista a mao, a fonte agora e o proprio run_pipeline.py: todo
# script que ele invoca via `_p("scripts", "nome.py")`. Script morto (nao
# chamado pelo run_pipeline.py) fica fora do fence de proposito — o mesmo
# raciocinio de "blast radius real" do fix round 1, so que auditavel por
# grep em vez de mantido a mao.
def _scripts_vivos():
    """Scripts que run_pipeline.py de fato executa, lidos dele mesmo."""
    src = io.open(ROOT / "run_pipeline.py", encoding="utf-8").read()
    nomes = sorted(set(re.findall(r'"scripts",\s*"([0-9a-zA-Z_]+\.py)"', src)))
    assert nomes, "nenhum script encontrado em run_pipeline.py — teste inutil"
    return [f"scripts/{n}" for n in nomes]


SCRIPTS = _scripts_vivos()

# Nome do arquivo -> tarefa do plano que o cria, para o motivo do skip.
CRIADO_NA_TASK = {
    "scripts/08b_background_image.py": "Task 4",
}


def _referenced(script_rel):
    """Acessores kpaths.X citados no script.

    A maioria dos scripts importa `import karaoke.paths as kpaths`, mas tres
    dos estagios vivos (03_forced_align_sofa.py, 03b_rosvot_inference.py,
    05_mfa_to_json.py) usam `from karaoke import paths` — mesmo modulo, alias
    diferente. Um regex so em "kpaths\\." examina esses tres arquivos com
    lista vazia (falso vazio, nao falta real) e cai no proprio guard de
    cardinalidade abaixo. Os dois aliases usados de fato no repo, confirmado
    por grep — nao um padrao especulativo.
    """
    src = io.open(ROOT / script_rel, encoding="utf-8").read()
    return sorted(set(re.findall(r"\b(?:kpaths|paths)\.([a-zA-Z_0-9]+)", src)))


@pytest.mark.parametrize("script_rel", SCRIPTS)
def test_todo_acessor_citado_existe(script_rel):
    if not (ROOT / script_rel).exists():
        task = CRIADO_NA_TASK.get(script_rel, "uma tarefa futura")
        pytest.skip(f"{script_rel} ainda nao existe — criado na {task}")
    names = _referenced(script_rel)
    assert names, f"nenhum kpaths.X encontrado em {script_rel} — teste inutil"
    missing = [n for n in names if not hasattr(kpaths, n)]
    assert not missing, (
        f"{script_rel}: {len(missing)} de {len(names)} acessores ausentes: {missing}"
    )


def test_acessores_novos_devolvem_path_absoluto():
    novos = [
        "adlibs_json", "input_video", "input_thumb", "output_video",
        "input_job_dir", "background_png", "demucs_out_dir",
    ]
    for name in novos:
        p = getattr(kpaths, name)("job_teste")
        assert isinstance(p, Path), f"{name} nao devolveu Path"
        assert p.is_absolute(), f"{name} devolveu caminho relativo: {p}"
        assert "job_teste" in str(p), f"{name} ignorou o job_id: {p}"


def test_input_job_dir_e_demucs_out_dir_nao_colidem():
    """Fence do defeito real do fix round 1: input_job_dir e demucs_out_dir
    carregam significados diferentes e nao podem apontar pro mesmo lugar.

    input_job_dir e o diretorio real de input — 01_media_prep.py escreve
    song.wav direto nele, 02_vocal_isolation.py e 13_process_conclusion.py
    leem/escrevem nele do mesmo jeito.

    demucs_out_dir e a subpasta que o Demucs cria em separation_dir/htdemucs/,
    nomeada pelo stem do arquivo de audio de entrada (song.wav -> "song"),
    nao pelo diretorio de input — ver scripts/02_vocal_isolation.py.
    """
    job_id = "job_teste"
    input_job = kpaths.input_job_dir(job_id)
    demucs_out = kpaths.demucs_out_dir(job_id)

    # input_job_dir e o diretorio real onde song.wav mora direto (sem
    # subpasta extra) — e o que 01_media_prep.py/02_vocal_isolation.py
    # assumem ao fazer `kpaths.input_job_dir(job_id) / "song.wav"`.
    assert input_job == kpaths.input_dir(job_id), (
        f"input_job_dir teria que ser o diretorio de input real, veio {input_job}"
    )
    assert (input_job / "song.wav").parent == input_job

    # demucs_out_dir mora dentro de separation_dir/htdemucs, nunca dentro do
    # diretorio de input.
    assert kpaths.separation_dir(job_id) in demucs_out.parents, (
        f"demucs_out_dir tem que ficar sob separation_dir, veio {demucs_out}"
    )
    assert "htdemucs" in demucs_out.parts

    # Os dois nunca podem colidir no mesmo caminho.
    assert input_job != demucs_out, (
        "input_job_dir e demucs_out_dir colidiram no mesmo caminho — "
        "um nome carregando dois significados e exatamente o defeito do fix round 1"
    )
