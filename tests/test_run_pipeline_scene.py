import run_pipeline as rp


def _nomes(steps):
    return [s["name"] for s in steps]


def test_sem_cena_lista_nao_muda():
    assert "Scene Background" not in _nomes(rp.build_steps("j", "pt", "none"))
    assert len(rp.build_steps("j", "pt", "none")) == 14


def test_com_cena_roda_08c_entre_ilustracao_e_render():
    steps = rp.build_steps("j", "pt", "none", scene="guts_camp")
    n = _nomes(steps)
    i = n.index("Scene Background")
    assert n[i - 1] == "Background Illustration" and n[i + 1] == "Video Rendering"
    cmd = steps[i]["cmd"]
    assert cmd[1].endswith("08c_scene_background.py")
    assert cmd[-2:] == ["--scene", "guts_camp"]


def _render(steps):
    return next(s for s in steps if s["name"] == "Video Rendering")["cmd"]


def test_com_cena_o_render_recebe_scene():
    assert _render(rp.build_steps("j", "pt", "none", scene="guts_camp"))[-2:] == ["--scene", "guts_camp"]


def test_sem_cena_o_render_nao_recebe_scene():
    assert "--scene" not in _render(rp.build_steps("j", "pt", "none"))
