"""Contrato: todo kpaths.X citado nos scripts de render tem de existir."""
import io
import re
from pathlib import Path

import pytest

import karaoke.paths as kpaths

ROOT = Path(__file__).resolve().parent.parent

# Todo script que referencia kpaths.input_job_dir ou kpaths.demucs_out_dir —
# os dois acessores no centro do defeito corrigido no fix round 1 (um nome,
# dois significados incompativeis: diretorio real de input vs. subpasta que
# o Demucs cria em htdemucs/). Isso e a "blast radius" real do bug, resolvida
# via grep de todos os call sites de input_job_dir no repo, um a um — nao um
# glob sobre scripts/*.py.
#
# Por que nao "todo scripts/*.py"? Um scan completo (rodado manualmente
# durante este fix) mostra ~10 acessores ausentes adicionais em scripts sem
# relacao com input_job_dir/demucs_out_dir — alguns em scripts efetivamente
# mortos (02b_trim_preview.py, 03_forced_align.py, 03b_whisperx_rescue.py,
# 03c_gemini_transcribe.py, 07_qc_report.py, 08_render_video.py,
# 09_audio_mixing.py — nao chamados por run_pipeline.py nem server.py) e
# outros em scripts que run_pipeline.py/server.py chamam de fato
# (03_prepare_corpus.py, 06_alignment_rescue.py, 07_gemini_alignment.py —
# `corpus_dir`, `char_timing_json`, `lyrics_txt` ausentes). Esses ultimos sao
# um defeito real, mas de uma familia diferente (nomes nunca criados, nao
# nomes com dois significados) e exigiriam a mesma investigacao rigorosa
# feita aqui para cada acessor — fora do escopo deste fix round. Registrado
# para decisao do coordenador, nao corrigido silenciosamente.
SCRIPTS = [
    "scripts/09_video_rendering.py",
    "scripts/08b_background_image.py",
    "scripts/01_media_prep.py",
    "scripts/02_vocal_isolation.py",
    "scripts/11_system_cleanup.py",
    "scripts/13_process_conclusion.py",
]

# Nome do arquivo -> tarefa do plano que o cria, para o motivo do skip.
CRIADO_NA_TASK = {
    "scripts/08b_background_image.py": "Task 4",
}


def _referenced(script_rel):
    src = io.open(ROOT / script_rel, encoding="utf-8").read()
    return sorted(set(re.findall(r"kpaths\.([a-zA-Z_0-9]+)", src)))


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
