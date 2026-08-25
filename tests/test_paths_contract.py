"""Contrato: todo kpaths.X citado nos scripts de render tem de existir."""
import io
import re
from pathlib import Path

import pytest

import karaoke.paths as kpaths

ROOT = Path(__file__).resolve().parent.parent

# Lista escrita a mao (os 6 scripts do fix round 1) deixou passar 3 acessores
# ausentes em estagios que o pipeline de fato executa (Task 5B). Em vez de mais
# uma lista a mao, a fonte agora sao os PROPRIOS entry points: todo script que
# eles invocam via `_p("scripts", "nome.py")`. Sao dois — run_pipeline.py (CLI)
# e server.py (o que o README manda rodar). Derivar so do run_pipeline.py
# deixava de fora os scripts que so o server.py chama; foi por essa fresta que
# uma classe inteira de defeito sobreviveu antes neste branch.
ENTRY_POINTS = ("run_pipeline.py", "server.py")


def _scripts_vivos():
    """(script, entry point que o invoca), lidos dos entry points reais.

    Uniao deduplicada: quando os dois invocam o mesmo script, fica registrado o
    primeiro da tupla acima — o motivo do skip precisa nomear ALGUM entry point
    real, nao os dois. Script morto (nenhum entry point o chama) fica fora do
    fence de proposito: mesmo raciocinio de "blast radius real" do fix round 1,
    so que auditavel por grep em vez de mantido a mao.
    """
    dono = {}
    for entry in ENTRY_POINTS:
        src = io.open(ROOT / entry, encoding="utf-8").read()
        for nome in re.findall(r'"scripts",\s*"([0-9a-zA-Z_]+\.py)"', src):
            dono.setdefault(nome, entry)
    assert dono, f"nenhum script encontrado em {ENTRY_POINTS} — teste inutil"
    # Os proprios entry points entram no fence: eles tambem citam kpaths.X
    # (server.py cita 15) e um acessor ausente ali estoura ANTES de qualquer
    # estagio rodar — foi exatamente o caso de kpaths.song_wav em server.py:95.
    return sorted([(f"scripts/{n}", e) for n, e in dono.items()]
                  + [(e, e) for e in ENTRY_POINTS])


SCRIPTS = _scripts_vivos()


def test_o_fence_cobre_os_dois_entry_points():
    """Cardinalidade do proprio fence: se a extracao quebrar em um dos entry
    points, o parametrize encolhe e todo o resto fica verde por vacuidade."""
    entries = {e for _, e in SCRIPTS}
    assert entries == set(ENTRY_POINTS), (
        f"{len(SCRIPTS)} scripts vindos de {sorted(entries)}; "
        f"esperado contribuicao dos {len(ENTRY_POINTS)} entry points"
    )


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


@pytest.mark.parametrize("script_rel,entry", SCRIPTS)
def test_todo_acessor_citado_existe(script_rel, entry):
    if not (ROOT / script_rel).exists():
        # Nao some em silencio: o skip nomeia quem referencia o arquivo que
        # nao existe no disco (run_sofa.py / run_rosvot.py, citados so pelo
        # server.py, sao os casos reais hoje).
        pytest.skip(f"{script_rel} nao existe no disco — referenciado por {entry}")
    names = _referenced(script_rel)
    assert names, f"nenhum kpaths.X encontrado em {script_rel} — teste inutil"
    missing = [n for n in names if not hasattr(kpaths, n)]
    assert not missing, (
        f"{script_rel}: {len(missing)} de {len(names)} acessores ausentes: {missing}"
    )


def test_acessores_novos_devolvem_path_absoluto():
    novos = [
        "adlibs_json", "output_video", "input_job_dir",
        "background_png", "demucs_out_dir",
    ]
    assert len(novos) >= 5, f"lista de acessores novos encolheu para {len(novos)}"
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
