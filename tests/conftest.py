"""Shared fixtures for the karaoke TDD suite."""
import io
import sys
import os
import pytest

# Ensure the project root is importable when running from anywhere
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
TEXTGRID_DIR = os.path.join(FIXTURES_DIR, "textgrids")
EXPECTED_DIR = os.path.join(FIXTURES_DIR, "expected")


def load_textgrid(name: str) -> str:
    path = os.path.join(TEXTGRID_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


import contextlib


@contextlib.contextmanager
def stdout_protegido():
    """Isola o `sys.stdout` de um import de script. USE EM VOLTA do exec_module.

    18 dos 26 arquivos em scripts/ fazem, no nivel de modulo:

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    Sob pytest esse buffer e o arquivo temporario da captura por fd. O wrapper
    toma POSSE dele: ao ser coletado, FECHA o temporario, e todo teste seguinte
    estoura "I/O operation on closed file" no setup e no teardown — longe do
    arquivo culpado, o que torna o rastro quase ilegivel.

    `detach()` devolve o buffer sem fechar. So reatribuir `sys.stdout` nao
    bastaria: o wrapper orfao ainda fecharia o temporario ao ser coletado.

    Por que gerenciador de contexto e nao fixture autouse: um fixture so
    desmonta DEPOIS que a captura do pytest ja desmontou, e ai o estrago ja
    aconteceu. Medido — a versao autouse deixou os 209 erros intactos. A
    restauracao precisa ser imediata, na linha seguinte ao exec_module.
    """
    orig_out, orig_err = sys.stdout, sys.stderr
    try:
        yield
    finally:
        for atual, orig in ((sys.stdout, orig_out), (sys.stderr, orig_err)):
            if atual is not orig and isinstance(atual, io.TextIOWrapper):
                try:
                    atual.detach()
                except Exception:
                    pass      # ja destacado ou sem buffer: nada a soltar
        sys.stdout, sys.stderr = orig_out, orig_err
