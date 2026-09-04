#!/usr/bin/env python
"""Estado das branches contra o tronco, e os comandos de arquivamento.

Reporta. Nao apaga nada: `--reap` imprime os comandos para voce colar.
Deletar branch e destrutivo e raro; automatizar compraria risco sem
comprar tempo.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections import Counter
from datetime import date
from typing import NamedTuple

TRUNK = "mvp-pipeline-runner"
PROTECTED = frozenset({"mvp-pipeline-runner", "master", "main"})
STALE_DAYS = 14
NOME_SEGURO = re.compile(r"^[A-Za-z0-9._/-]+$")


class Branch(NamedTuple):
    name: str
    sha: str
    last: date
    subject: str
    merge_base: bool
    behind: int
    ahead: int
    worktree: str
    dirty: int


def verdict(b: Branch, today: date, stale_days: int = STALE_DAYS) -> str:
    """protegida > orfa > attic > viva. A ordem importa: protecao vem primeiro."""
    if b.name in PROTECTED:
        return "protegida"
    if not b.merge_base:
        return "orfa"
    if (today - b.last).days > stale_days:
        return "attic"
    return "viva"


def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )


def _worktrees(cwd: str | None = None) -> dict[str, str]:
    """branch -> caminho do worktree que a tem checada."""
    out = _git("worktree", "list", "--porcelain", cwd=cwd).stdout
    mapa: dict[str, str] = {}
    atual = ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            atual = line[len("worktree ") :].strip()
        elif line.startswith("branch refs/heads/"):
            mapa[line.split("refs/heads/", 1)[1].strip()] = atual
    return mapa


def _dirty(path: str) -> int:
    """Quantas entradas nao commitadas o worktree tem. 0 se nao der para saber."""
    if not path or not os.path.isdir(path):
        return 0
    r = _git("status", "--porcelain", cwd=path)
    if r.returncode != 0:
        return 0
    return len([l for l in r.stdout.splitlines() if l.strip()])


def collect(cwd: str | None = None) -> list[Branch]:
    if _git("rev-parse", "--verify", "--quiet", TRUNK, cwd=cwd).returncode != 0:
        raise ValueError(f"tronco {TRUNK} nao existe neste repositorio")
    wts = _worktrees(cwd)
    fmt = "%(refname:short)%09%(objectname)%09%(committerdate:short)%09%(contents:subject)"
    out = _git("for-each-ref", f"--format={fmt}", "refs/heads", cwd=cwd).stdout
    rows: list[Branch] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        campos = line.split("\t", 3)
        while len(campos) < 4:
            campos.append("")
        name, sha, dia, subject = campos
        tem_base = _git("merge-base", TRUNK, name, cwd=cwd).returncode == 0
        behind = ahead = 0
        if tem_base:
            counts = _git(
                "rev-list", "--left-right", "--count", f"{TRUNK}...{name}", cwd=cwd
            ).stdout.split()
            if len(counts) == 2:
                behind, ahead = int(counts[0]), int(counts[1])
        rows.append(
            Branch(
                name=name,
                sha=sha,
                last=date.fromisoformat(dia),
                subject=subject,
                merge_base=tem_base,
                behind=behind,
                ahead=ahead,
                worktree=wts.get(name, ""),
                dirty=_dirty(wts.get(name, "")),
            )
        )
    return rows


def render(rows: list[Branch], today: date, stale_days: int = STALE_DAYS) -> str:
    linhas = []
    for b in sorted(rows, key=lambda x: x.last, reverse=True):
        v = verdict(b, today, stale_days)
        pos = "-" if not b.merge_base else f"{b.behind}/{b.ahead}"
        wt = ""
        if b.worktree:
            wt = f" [worktree, {b.dirty} sujo]" if b.dirty else " [worktree]"
        linhas.append(f"{v:<10} {b.last.isoformat()}  {pos:>9}  {b.name}{wt}")
    return "\n".join(linhas)


def summary(rows: list[Branch], today: date, stale_days: int = STALE_DAYS) -> str:
    total = len(rows)
    if total == 0:
        raise ValueError(
            "nenhuma branch encontrada — conjunto vazio nao e veredito verde"
        )
    c = Counter(verdict(b, today, stale_days) for b in rows)
    partes = [
        f"{k} {c[k]} de {total}"
        for k in ("viva", "protegida", "attic", "orfa")
        if c[k]
    ]
    return " | ".join(partes) + f"  (soma {sum(c.values())} = {total})"


def reap_commands(
    rows: list[Branch], today: date, stale_days: int = STALE_DAYS
) -> tuple[list[str], list[Branch]]:
    """Comandos de arquivamento. Nao executa nada — devolve texto para colar."""
    cmds: list[str] = []
    bloqueadas: list[Branch] = []
    for b in rows:
        if verdict(b, today, stale_days) not in ("orfa", "attic"):
            continue
        if b.worktree or not NOME_SEGURO.match(b.name):
            bloqueadas.append(b)
            continue
        cmds.append(f"git tag attic/{b.name} {b.sha} && git branch -D {b.name}")
    return cmds, bloqueadas


def remedios(bloqueadas: list[Branch]) -> list[str]:
    """Uma secao por motivo de bloqueio.

    Worktree sujo NAO ganha comando de remocao: `git worktree remove` sobre
    arvore suja destroi trabalho nao commitado. O script nao decide isso por
    voce — ele nomeia o que ha para perder.
    """
    total = len(bloqueadas)
    limpas = [b for b in bloqueadas if b.worktree and not b.dirty]
    sujas = [b for b in bloqueadas if b.worktree and b.dirty]
    inseguras = [b for b in bloqueadas if not b.worktree]
    linhas: list[str] = []
    if limpas:
        linhas.append(f"# {len(limpas)} de {total}: worktree limpo. Remova e rode de novo:")
        for b in limpas:
            linhas.append(f"git worktree remove {b.worktree}   # {b.name}")
    if sujas:
        linhas.append(f"# {len(sujas)} de {total}: worktree SUJO. NAO remova — resolva antes:")
        for b in sujas:
            linhas.append(f"#   {b.name}: {b.dirty} nao commitadas em {b.worktree}")
    if inseguras:
        linhas.append(
            f"# {len(inseguras)} de {total}: nome exige aspas. "
            "Renomeie (`git branch -m <atual> <seguro>`) e rode de novo:"
        )
        for b in inseguras:
            linhas.append(f"#   {b.name}")
    return linhas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Estado das branches contra o tronco.")
    p.add_argument(
        "--reap",
        action="store_true",
        help="imprime os comandos de arquivamento; nao executa nada",
    )
    p.add_argument("--stale-days", type=int, default=STALE_DAYS)
    a = p.parse_args(argv)

    rows = collect()
    hoje = date.today()
    print(render(rows, hoje, a.stale_days))
    print()
    print(summary(rows, hoje, a.stale_days))

    if a.reap:
        cmds, bloqueadas = reap_commands(rows, hoje, a.stale_days)
        print()
        print(f"# {len(cmds)} de {len(rows)} branches a arquivar. Cole:")
        for c in cmds:
            print(c)
        if bloqueadas:
            print(f"# {len(bloqueadas)} de {len(rows)} nao podem ser apagadas agora:")
            for linha in remedios(bloqueadas):
                print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
