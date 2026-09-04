#!/usr/bin/env python
"""Estado das branches contra o tronco, e os comandos de arquivamento.

Reporta. Nao apaga nada: `--reap` imprime os comandos para voce colar.
Deletar branch e destrutivo e raro; automatizar compraria risco sem
comprar tempo.
"""
from __future__ import annotations

import argparse
import subprocess
from collections import Counter
from datetime import date
from typing import NamedTuple

TRUNK = "mvp-pipeline-runner"
PROTECTED = frozenset({"mvp-pipeline-runner", "master", "main"})
STALE_DAYS = 14


class Branch(NamedTuple):
    name: str
    sha: str
    last: date
    subject: str
    merge_base: bool
    behind: int
    ahead: int
    checked_out: bool


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


def _checked_out(cwd: str | None = None) -> set[str]:
    out = _git("worktree", "list", "--porcelain", cwd=cwd).stdout
    return {
        line.split("refs/heads/", 1)[1].strip()
        for line in out.splitlines()
        if line.startswith("branch refs/heads/")
    }


def collect(cwd: str | None = None, trunk: str = TRUNK) -> list[Branch]:
    ativos = _checked_out(cwd)
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
        tem_base = _git("merge-base", trunk, name, cwd=cwd).returncode == 0
        behind = ahead = 0
        if tem_base:
            counts = _git(
                "rev-list", "--left-right", "--count", f"{trunk}...{name}", cwd=cwd
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
                checked_out=name in ativos,
            )
        )
    return rows


def render(rows: list[Branch], today: date, stale_days: int = STALE_DAYS) -> str:
    linhas = []
    for b in sorted(rows, key=lambda x: x.last, reverse=True):
        v = verdict(b, today, stale_days)
        pos = "-" if not b.merge_base else f"{b.behind}/{b.ahead}"
        wt = " [worktree]" if b.checked_out else ""
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Estado das branches contra o tronco.")
    p.add_argument("--stale-days", type=int, default=STALE_DAYS)
    a = p.parse_args(argv)
    rows = collect()
    hoje = date.today()
    print(render(rows, hoje, a.stale_days))
    print()
    print(summary(rows, hoje, a.stale_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
