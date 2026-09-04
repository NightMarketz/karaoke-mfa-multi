"""Cercas da classificacao de branches contra o tronco.

Traz o proprio controle negativo: ver os passos de sabotagem no plano.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import branch_harvest as bh

HOJE = date(2026, 9, 4)


def _b(name, last, merge_base=True, checked_out=False, ahead=1, behind=0):
    return bh.Branch(
        name=name,
        sha="0" * 40,
        last=last,
        subject="assunto",
        merge_base=merge_base,
        behind=behind,
        ahead=ahead,
        checked_out=checked_out,
    )


def test_protegida_vence_o_relogio():
    # master esta velho e mergeavel; protecao tem de vir antes do relogio
    b = _b("master", date(2026, 8, 15))
    assert bh.verdict(b, HOJE) == "protegida"


def test_protegida_vence_a_linhagem():
    # main esta na outra linhagem; protecao tem de vir antes de P1 tambem
    b = _b("main", date(2026, 3, 15), merge_base=False)
    assert bh.verdict(b, HOJE) == "protegida"


def test_sem_ancestral_comum_e_orfa_mesmo_recente():
    b = _b("claude/kind-blackburn-cd1944", date(2026, 9, 4), merge_base=False)
    assert bh.verdict(b, HOJE) == "orfa"


def test_limiar_do_relogio_exatamente_14_dias_sobrevive():
    # 2026-08-21 esta a 14 dias de 2026-09-04. "mais de 14" nao inclui 14.
    b = _b("claude/no-limiar", date(2026, 8, 21))
    assert (HOJE - b.last).days == 14
    assert bh.verdict(b, HOJE) == "viva"


def test_limiar_do_relogio_15_dias_vai_para_attic():
    b = _b("claude/um-dia-alem", date(2026, 8, 20))
    assert (HOJE - b.last).days == 15
    assert bh.verdict(b, HOJE) == "attic"


def test_summary_traz_denominador_e_fecha_a_soma():
    rows = [
        _b("mvp-pipeline-runner", date(2026, 8, 20)),
        _b("claude/viva", date(2026, 9, 1)),
        _b("claude/velha", date(2026, 1, 1)),
        _b("claude/orfa", date(2026, 9, 1), merge_base=False),
    ]
    out = bh.summary(rows, HOJE)
    assert "de 4" in out
    assert "soma 4 = 4" in out
    assert "protegida 1 de 4" in out
    assert "viva 1 de 4" in out
    assert "attic 1 de 4" in out
    assert "orfa 1 de 4" in out


def test_summary_recusa_conjunto_vazio():
    # zero branches nao e veredito verde
    with pytest.raises(ValueError):
        bh.summary([], HOJE)


def test_render_mostra_uma_linha_por_branch_com_veredito():
    rows = [_b("claude/viva", date(2026, 9, 1)), _b("claude/velha", date(2026, 1, 1))]
    linhas = bh.render(rows, HOJE).splitlines()
    assert len(linhas) == 2
    assert "viva" in linhas[0] and "claude/viva" in linhas[0]
    assert "attic" in linhas[1] and "claude/velha" in linhas[1]


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def test_collect_le_o_git_de_verdade(tmp_path):
    """Integracao: valida as strings de comando git, nao a logica pura."""
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-b", bh.TRUNK, cwd=r)
    _git("config", "user.email", "t@t.local", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "a.txt").write_text("1", encoding="utf-8")
    _git("add", "-A", cwd=r)
    _git("commit", "-m", "tronco", cwd=r)

    # branch mergeavel, um commit a frente
    _git("checkout", "-b", "feature-mergeavel", cwd=r)
    (r / "b.txt").write_text("2", encoding="utf-8")
    _git("add", "-A", cwd=r)
    _git("commit", "-m", "adiciona b", cwd=r)

    # branch sem ancestral comum
    _git("checkout", "--orphan", "feature-orfa", cwd=r)
    _git("rm", "-rf", ".", cwd=r)
    (r / "c.txt").write_text("3", encoding="utf-8")
    _git("add", "-A", cwd=r)
    _git("commit", "-m", "raiz separada", cwd=r)

    rows = {b.name: b for b in bh.collect(cwd=str(r))}
    assert len(rows) == 3, f"esperava 3 branches, vi {len(rows)}: {sorted(rows)}"

    assert rows["feature-mergeavel"].merge_base is True
    assert rows["feature-mergeavel"].ahead == 1
    assert rows["feature-mergeavel"].behind == 0

    assert rows["feature-orfa"].merge_base is False
    assert bh.verdict(rows["feature-orfa"], HOJE) == "orfa"

    # a branch com worktree ativo tem de vir marcada
    assert rows["feature-orfa"].checked_out is True
    assert rows[bh.TRUNK].checked_out is False


def test_collect_recusa_repositorio_sem_tronco(tmp_path):
    """Sem o tronco, merge-base falha por ref desconhecida (exit 128), nao por
    ausencia de ancestral comum (exit 1) — os dois nao podem virar 'orfa'."""
    r = tmp_path / "repo-sem-tronco"
    r.mkdir()
    _git("init", "-b", "so-existe-esta", cwd=r)
    _git("config", "user.email", "t@t.local", cwd=r)
    _git("config", "user.name", "t", cwd=r)
    (r / "a.txt").write_text("1", encoding="utf-8")
    _git("add", "-A", cwd=r)
    _git("commit", "-m", "unica branch", cwd=r)

    with pytest.raises(ValueError, match=bh.TRUNK):
        bh.collect(cwd=str(r))


def test_reap_emite_tag_antes_do_delete():
    b = _b("claude/velha", date(2026, 1, 1))
    cmds, bloqueadas = bh.reap_commands([b], HOJE)
    assert bloqueadas == []
    assert len(cmds) == 1
    assert cmds[0].index("git tag attic/claude/velha") < cmds[0].index("git branch -D")
    assert "&&" in cmds[0], "delete nao pode rodar se a tag falhar"
    assert b.sha in cmds[0], "sem o sha a tag marca o HEAD atual, nao a branch"


def test_reap_pula_branch_com_worktree_ativo():
    b = _b("claude/velha-em-uso", date(2026, 1, 1), checked_out=True)
    cmds, bloqueadas = bh.reap_commands([b], HOJE)
    assert cmds == []
    assert bloqueadas == ["claude/velha-em-uso"]


def test_reap_bloqueia_nome_com_metacaractere_de_shell():
    # nome de branch cru dentro do comando: `;`, `$(...)`, etc. executariam
    # ao colar. Tem de ir para bloqueadas, nunca virar linha de comando.
    b = _b("evil;pwned", date(2026, 1, 1))
    cmds, bloqueadas = bh.reap_commands([b], HOJE)
    assert cmds == []
    assert bloqueadas == ["evil;pwned"]


def test_reap_ignora_viva_e_protegida():
    rows = [
        _b("mvp-pipeline-runner", date(2026, 1, 1)),
        _b("claude/viva", date(2026, 9, 1)),
    ]
    cmds, bloqueadas = bh.reap_commands(rows, HOJE)
    assert cmds == []
    assert bloqueadas == []


def test_reap_arquiva_orfa_e_attic_juntas():
    rows = [
        _b("claude/orfa", date(2026, 9, 1), merge_base=False),
        _b("claude/velha", date(2026, 1, 1)),
    ]
    cmds, _ = bh.reap_commands(rows, HOJE)
    assert len(cmds) == 2


def test_contagem_fecha_por_caminho_independente():
    """Re-derivacao: as listas de saida somam o total, usando o mesmo oraculo
    (bh.verdict) do outro lado — nao prova a logica de reap_commands por um
    caminho independente, so prova que nenhuma branch se perde entre os baldes.

    Pega uma branch sumindo de todos os baldes (perdida na contagem). Nao pega
    uma branch trocando de balde (ex.: de bloqueada para cmds) — a soma
    len(cmds) + len(bloqueadas) fica igual nos dois casos.
    """
    rows = [
        _b("mvp-pipeline-runner", date(2026, 8, 20)),              # protegida
        _b("master", date(2026, 8, 15)),                           # protegida
        _b("claude/viva", date(2026, 9, 1)),                       # viva
        _b("claude/velha", date(2026, 1, 1)),                      # attic
        _b("claude/em-uso", date(2026, 1, 1), checked_out=True),   # attic, bloqueada
        _b("claude/orfa", date(2026, 9, 1), merge_base=False),     # orfa
    ]
    cmds, bloqueadas = bh.reap_commands(rows, HOJE)
    sobreviventes = [b for b in rows if bh.verdict(b, HOJE) in ("viva", "protegida")]
    assert len(cmds) + len(bloqueadas) + len(sobreviventes) == len(rows) == 6
