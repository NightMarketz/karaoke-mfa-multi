# Colheita de branches — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao processo de colheita as duas peças que faltam — uma medição de linha de base da suíte no tronco, e um comando que classifica as branches contra o tronco e emite os comandos de arquivamento.

**Architecture:** Um script Python único, `scripts/branch_harvest.py`, dividido em uma camada de coleta (fala com o git) e uma camada de classificação (função pura, sem I/O). A classificação é o que os testes atacam; a coleta tem um teste de integração sobre um repositório temporário construído no próprio teste. O script **nunca apaga nada**: `--reap` imprime os comandos para colar. Deletar branch é destrutivo e raro; automatizá-lo compraria risco sem comprar tempo.

**Tech Stack:** Python 3.10 (stdlib apenas: `argparse`, `subprocess`, `datetime`, `collections`, `typing`), git CLI, pytest.

## Global Constraints

- Spec de origem: `docs/superpowers/specs/2026-09-04-colheita-de-branches-design.md`.
- Tronco: `mvp-pipeline-runner`. Refs protegidas: `mvp-pipeline-runner`, `master`, `main`.
- Janela do relógio: 14 dias. Morre quem tem **mais de** 14 dias sem commit (`> 14`, não `>=`).
- Prefixo de arquivamento: `attic/<nome>`.
- Comando de teste, sempre com o argumento: `pytest tests`. Nunca `pytest` na raiz — sem o argumento, `pytest.importorskip` vira erro de coleta e o número medido é de outra população.
- Zero dependências novas. Só stdlib.
- Todo número impresso pelo script sai com denominador ("29 de 42"), e a soma das partes fecha com o total por um caminho independente.
- Conjunto vazio não é veredito verde: zero branches é erro, não sucesso.
- **Todo teste de lógica não-trivial tem controle negativo:** sabote o alvo, confirme vermelho, desfaça, confirme verde. Os passos de sabotagem estão escritos em cada tarefa e não são opcionais.

---

### Task 1: Medir a linha de base da suíte no tronco (Lacuna L3)

Bloqueia todas as outras. O portão de merge do spec compara "depois do merge" com "antes do merge"; sem o "antes", o primeiro merge reprovado não distingue *a branch quebrou* de *já estava quebrado*.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-04-colheita-de-branches-design.md` (seção 11, lacuna L3)

**Interfaces:**
- Consumes: nada.
- Produces: dois números com denominador, registrados no spec, que as tarefas seguintes citam como "linha de base do tronco".

- [ ] **Step 1: Confirmar que está no tronco**

```bash
cd "C:/Users/Katz/OneDrive/Desktop/Meus projetos/karaoke-mfa-multi" && git rev-parse --abbrev-ref HEAD
```

Esperado: `mvp-pipeline-runner`. Se não for, pare — medir a suíte de outra branch produz um número que não é a linha de base.

- [ ] **Step 2: Contar a população antes de rodar**

```bash
git ls-files 'tests/test_*.py' | wc -l
```

Esperado hoje: `67`. Esse é o denominador de arquivos. Anote.

- [ ] **Step 3: Rodar a suíte, guardando a saída inteira**

```bash
pytest tests 2>&1 | tee baseline-tronco.txt | tail -30
```

Não descarte a saída. A linha de resumo do pytest (`N passed, M failed, K errors in Xs`) e a linha de coleta (`collected N items`) são as duas medições. O arquivo `baseline-tronco.txt` é temporário e não deve ser commitado.

- [ ] **Step 4: Checar erro de coleta separadamente**

```bash
grep -cE "^ERROR |errors? during collection" baseline-tronco.txt
```

Erro de coleta não é teste falhando — é teste que nem rodou, e infla ou esconde o resultado. Se houver algum, registre o número e o arquivo, e **não** o some aos falhos.

- [ ] **Step 5: Registrar no spec, com denominador**

Substitua o parágrafo da lacuna L3 em `docs/superpowers/specs/2026-09-04-colheita-de-branches-design.md` por este texto, preenchendo com os números reais medidos:

```markdown
**L3 — FECHADA em 2026-09-04.** Linha de base do tronco, medida com `pytest tests`
sobre 67 arquivos `test_*.py`:

- coletados: `<N>` itens
- passaram: `<P>` de `<N>`
- falharam: `<F>` de `<N>`
- erros de coleta: `<E>` (arquivos: `<lista>`)
- soma: `<P>` + `<F>` = `<N>`

O portão de merge compara contra esses números. Merge que não aumente `<F>` passa,
mesmo com a suíte já vermelha; merge que aumente, reprova.
```

Se a soma não fechar, **não invente a diferença** — investigue (skip, xfail e deselect aparecem no resumo e mudam o denominador) e registre a categoria que faltava.

- [ ] **Step 6: Commit**

```bash
rm -f baseline-tronco.txt && git add -- docs/superpowers/specs/2026-09-04-colheita-de-branches-design.md && git commit -m "docs: fecha a lacuna L3 com a linha de base medida do tronco"
```

---

### Task 2: Classificação e relatório de estado

**Files:**
- Create: `scripts/branch_harvest.py`
- Test: `tests/test_branch_harvest.py`

**Interfaces:**
- Consumes: a linha de base da Task 1 (só como contexto, não como código).
- Produces:
  - `Branch` — `NamedTuple(name: str, sha: str, last: datetime.date, subject: str, merge_base: bool, behind: int, ahead: int, checked_out: bool)`
  - `verdict(b: Branch, today: date, stale_days: int = 14) -> str` — devolve `"protegida"`, `"orfa"`, `"attic"` ou `"viva"`
  - `collect(cwd: str | None = None, trunk: str = TRUNK) -> list[Branch]`
  - `render(rows: list[Branch], today: date, stale_days: int = 14) -> str`
  - `summary(rows: list[Branch], today: date, stale_days: int = 14) -> str`
  - Constantes `TRUNK`, `PROTECTED`, `STALE_DAYS`

- [ ] **Step 1: Escrever os testes que falham**

Crie `tests/test_branch_harvest.py`:

```python
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
```

- [ ] **Step 2: Rodar e confirmar que falha por ausência do módulo**

```bash
pytest tests/test_branch_harvest.py -v
```

Esperado: erro de coleta, `ModuleNotFoundError: No module named 'branch_harvest'`. É o vermelho certo — o módulo não existe ainda.

- [ ] **Step 3: Escrever a implementação mínima**

Crie `scripts/branch_harvest.py`:

```python
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
```

- [ ] **Step 4: Rodar os testes e confirmar verde**

```bash
pytest tests/test_branch_harvest.py -v
```

Esperado: 9 passed. Se `test_collect_le_o_git_de_verdade` falhar em `checked_out`, confirme que `git worktree list --porcelain` no repositório temporário emite `branch refs/heads/feature-orfa` — é o formato que o parser espera.

- [ ] **Step 5: Controle negativo do limiar (não é passo opcional)**

Em `scripts/branch_harvest.py`, dentro de `verdict`, troque `if (today - b.last).days > stale_days:` por `if (today - b.last).days >= stale_days:`. Rode:

```bash
pytest tests/test_branch_harvest.py -v
```

Esperado: `test_limiar_do_relogio_exatamente_14_dias_sobrevive` **FALHA** (devolve `attic`, esperava `viva`). Se passar, o teste do limiar não é cerca — está afirmando algo que a implementação não decide. **Desfaça a troca** e confirme verde de novo antes de seguir.

- [ ] **Step 6: Controle negativo da precedência**

Em `verdict`, mova o bloco `if b.name in PROTECTED: return "protegida"` para **depois** do bloco `if not b.merge_base: return "orfa"`. Rode:

```bash
pytest tests/test_branch_harvest.py -v
```

Esperado: `test_protegida_vence_a_linhagem` **FALHA** (devolve `orfa`). **Desfaça** e confirme verde.

- [ ] **Step 7: Rodar a suíte inteira e comparar com a linha de base**

```bash
pytest tests
```

Esperado: os mesmos números da Task 1, mais 9 testes passando. Se algum teste que passava antes falhar agora, é regressão desta tarefa — investigue antes de commitar.

- [ ] **Step 8: Commit**

```bash
git add -- scripts/branch_harvest.py tests/test_branch_harvest.py && git commit -m "feat(harvest): classifica branches contra o tronco, com cercas de limiar e precedencia"
```

---

### Task 3: Emissão dos comandos de arquivamento (`--reap`)

**Files:**
- Modify: `scripts/branch_harvest.py`
- Test: `tests/test_branch_harvest.py`

**Interfaces:**
- Consumes: `Branch`, `verdict`, `summary` da Task 2.
- Produces: `reap_commands(rows: list[Branch], today: date, stale_days: int = 14) -> tuple[list[str], list[str]]` — devolve `(comandos, bloqueadas)`, onde `bloqueadas` são os nomes das branches que têm worktree ativo e por isso não podem ser apagadas.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_branch_harvest.py`:

```python
def test_reap_emite_tag_antes_do_delete():
    b = _b("claude/velha", date(2026, 1, 1))
    cmds, bloqueadas = bh.reap_commands([b], HOJE)
    assert bloqueadas == []
    assert len(cmds) == 1
    assert cmds[0].index("git tag attic/claude/velha") < cmds[0].index("git branch -D")
    assert "&&" in cmds[0], "delete nao pode rodar se a tag falhar"


def test_reap_pula_branch_com_worktree_ativo():
    b = _b("claude/velha-em-uso", date(2026, 1, 1), checked_out=True)
    cmds, bloqueadas = bh.reap_commands([b], HOJE)
    assert cmds == []
    assert bloqueadas == ["claude/velha-em-uso"]


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
    """Re-derivacao: as listas de saida somam o total, sem consultar os vereditos."""
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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
pytest tests/test_branch_harvest.py -v -k reap
```

Esperado: `AttributeError: module 'branch_harvest' has no attribute 'reap_commands'`.

- [ ] **Step 3: Implementar**

Acrescente a `scripts/branch_harvest.py`, logo depois de `summary`:

```python
def reap_commands(
    rows: list[Branch], today: date, stale_days: int = STALE_DAYS
) -> tuple[list[str], list[str]]:
    """Comandos de arquivamento. Nao executa nada — devolve texto para colar."""
    cmds: list[str] = []
    bloqueadas: list[str] = []
    for b in rows:
        if verdict(b, today, stale_days) not in ("orfa", "attic"):
            continue
        if b.checked_out:
            bloqueadas.append(b.name)
            continue
        cmds.append(f"git tag attic/{b.name} {b.sha} && git branch -D {b.name}")
    return cmds, bloqueadas
```

E substitua `main` inteira por:

```python
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
            print(
                f"# {len(bloqueadas)} de {len(rows)} nao podem ser apagadas "
                "(worktree ativo): " + ", ".join(bloqueadas)
            )
            print(
                "# remedio: `git worktree list` para achar o caminho, "
                "`git worktree remove <caminho>`, depois rode este comando de novo."
            )
    return 0
```

- [ ] **Step 4: Rodar os testes e confirmar verde**

```bash
pytest tests/test_branch_harvest.py -v
```

Esperado: 14 passed.

- [ ] **Step 5: Controle negativo da ordem tag→delete**

Em `reap_commands`, troque a linha do `cmds.append(...)` por `cmds.append(f"git branch -D {b.name} && git tag attic/{b.name} {b.sha}")`. Rode:

```bash
pytest tests/test_branch_harvest.py -v -k reap
```

Esperado: `test_reap_emite_tag_antes_do_delete` **FALHA**. Essa cerca existe porque a ordem invertida perde o commit quando a tag falha. **Desfaça** e confirme verde.

- [ ] **Step 6: Controle negativo da guarda de worktree**

Remova de `reap_commands` as três linhas do bloco `if b.checked_out:`. Rode:

```bash
pytest tests/test_branch_harvest.py -v -k reap
```

Esperado: `test_reap_pula_branch_com_worktree_ativo` **FALHA**. (`test_contagem_fecha_por_caminho_independente` não é alvo deste controle: sua asserção soma `len(cmds) + len(bloqueadas)`, invariante a qual balde o item cai, então prova que nenhuma branch se perde na contagem, não que a guarda de worktree existe.) **Desfaça** e confirme verde.

- [ ] **Step 7: Rodar contra o repositório real e conferir com o medido no spec**

```bash
python scripts/branch_harvest.py --reap
```

Esperado, contra os números do spec (§2), com `--stale-days 14` e hoje ≈ 2026-09-04:
`viva 3 de 42 | protegida 2 de 42 | attic 8 de 42 | orfa 29 de 42  (soma 42 = 42)`.

Se a soma não fechar, ou se as parcelas não somarem 42, pare: ou o script está errado, ou o repositório mudou desde a medição. Nos dois casos, o número novo é que vale — e o spec precisa ser atualizado, não o número maquiado.

**Não cole os comandos ainda.** Executar a colheita é decisão do usuário, não do plano.

- [ ] **Step 8: Rodar a suíte inteira**

```bash
pytest tests
```

Esperado: linha de base da Task 1, mais 14 testes passando.

- [ ] **Step 9: Commit**

```bash
git add -- scripts/branch_harvest.py tests/test_branch_harvest.py && git commit -m "feat(harvest): emite os comandos de arquivamento, com tag antes do delete"
```

---

### Task 4: As linhas no `CLAUDE.md` do tronco

Mecanismo escolhido no spec (§9): fato curto, verdadeiro em toda sessão, sobre todo o repo. Não é skill.

**Files:**
- Modify: `CLAUDE.md` (raiz do tronco)
- Modify: `AGENTS.md` (raiz do tronco) — os dois são pares gêmeos no repositório; deixar um desatualizado recria a deriva que o spec ataca

**Interfaces:**
- Consumes: `scripts/branch_harvest.py` da Task 3.
- Produces: nada em código.

- [ ] **Step 1: Ler os arquivos atuais antes de editar**

```bash
cd "C:/Users/Katz/OneDrive/Desktop/Meus projetos/karaoke-mfa-multi" && diff CLAUDE.md AGENTS.md && echo "(identicos)" || echo "(divergem — veja o diff acima antes de editar)"
```

- [ ] **Step 2: Acrescentar a seção, em ambos os arquivos**

Texto exato, ao fim de `CLAUDE.md` **e** de `AGENTS.md`:

```markdown
## Tronco e colheita

- **Tronco:** `mvp-pipeline-runner`. Todo trabalho volta para cá. Refs protegidas,
  nunca arquivadas: `mvp-pipeline-runner`, `master`, `main`.
- **Comando de teste:** `pytest tests` — com o argumento. `pytest` na raiz mede
  outra população: transforma `pytest.importorskip` em erro de coleta.
- **Portão de merge:** `pytest tests` verde **no resultado do merge**, não na branch
  isolada. Vermelho desfaz o merge.
- **Colheita:** antes de despachar uma frente nova, rode
  `python scripts/branch_harvest.py --reap` e resolva o destino das branches
  existentes. Branch sem ancestral comum com o tronco não é mergeável — arquivar ou
  portar à mão, nunca `git merge`.
- Desenho e medição que originaram isto:
  `docs/superpowers/specs/2026-09-04-colheita-de-branches-design.md`.
```

- [ ] **Step 3: Verificar que o comando citado existe e roda**

```bash
python scripts/branch_harvest.py --reap | tail -5
```

Esperado: sai sem erro. Instrução que cita comando quebrado é pior que instrução ausente — foi exatamente o que aconteceu com o `README.md`.

- [ ] **Step 4: Commit**

```bash
git add -- CLAUDE.md AGENTS.md && git commit -m "docs: declara o tronco, o comando de teste e o gatilho da colheita"
```

---

## Fora deste plano

- **Executar a colheita.** O plano entrega o comando; apertar o gatilho sobre 37 branches é decisão do usuário, em sessão própria.
- **Consertar o `README.md`** da linhagem MAIN, que descreve um pipeline de 12 estágios que não roda (batem 3 de 12).
- **Portar qualquer coisa das 29 órfãs** — Lacuna L2 do spec, decidida por branch e sob demanda.
- **Hook de enforcement.** Nada aqui impede um merge sem teste; os portões dependem de serem rodados. Adicionar quando um merge ruim passar de fato — não antes.
