import importlib
import unittest


def import_or_skip(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise unittest.SkipTest(f"requires optional dependency {module_name}: {exc}") from exc
