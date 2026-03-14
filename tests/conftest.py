"""Shared fixtures for the karaoke TDD suite."""
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
