# tests/test_render_cmd.py
"""Contrato do comando ffmpeg. Monta a lista de args, nao roda o encoder."""
from pathlib import Path

from karaoke.render_cmd import WORK_H, WORK_W, build_render_cmd

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


def test_sendcmd_vem_antes_do_crop():
    # Mesma logica do test_scale_vem_depois_do_crop: se o sendcmd for
    # comandado DEPOIS do crop, o pulso nao tem mais o que encolher —
    # o encolhimento ja passou pelo filtro. Precisa vir antes.
    fc = _fc(build_render_cmd(BG, [INST, VOX], ASS, OUT, 210.0, SC))
    assert fc.index("sendcmd=f=") < fc.index("crop="), f"ordem errada: {fc}"


def test_crop_usa_work_w_work_h():
    # crop= no filtergraph tem que casar com as MESMAS constantes que o
    # script passa para build_sendcmd (WORK_W/WORK_H). Se elas driftarem
    # uma da outra, o sendcmd fica comandando um crop com dimensao errada
    # e nada acusa isso — so este teste.
    fc = _fc(build_render_cmd(BG, [INST, VOX], ASS, OUT, 210.0, SC))
    assert f"crop={WORK_W}:{WORK_H}" in fc, fc


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
    # Medido de fato contra o binario ffmpeg 8.1-full_build-www.gyan.dev via
    # subprocess.run com lista de args (sem shell): dentro do filtergraph
    # "C:/x" precisa virar 'C\:/x' (barra invertida, entre aspas simples).
    # Sem escape falha ("Error applying option 'original_size'" / "Invalid
    # argument"). Uma barra invertida e duas barras invertidas rodam as
    # duas (rc=0); usamos uma por ser a mais simples que ja funciona — nao
    # e a unica opcao que funciona, entao nao afirmamos isso aqui. Medir
    # isso pela linha de comando do bash da resultado errado (o shell come
    # um nivel de barra); so subprocess.run com lista de args conta. Os
    # demais testes deste arquivo usam caminhos /tmp/ sem dois-pontos — nao
    # pegariam isso.
    win_ass = Path(r"C:\jobs\k.ass")
    win_sc = Path(r"C:\jobs\bounce.txt")
    fc = _fc(build_render_cmd(BG, [INST, VOX], win_ass, OUT, 210.0, win_sc))
    assert "subtitles='C\\:/jobs/k.ass'" in fc, fc
    assert "sendcmd=f='C\\:/jobs/bounce.txt'" in fc, fc
