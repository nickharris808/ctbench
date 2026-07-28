"""Shared fixtures: the bundled corpus, read from the manifest that ships with it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "ctbench" / "fixtures"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def manifest() -> dict:
    return json.loads((FIXTURE_DIR / "manifest.json").read_text())


@pytest.fixture(scope="session")
def scored_manifest(manifest) -> list[dict]:
    return manifest["scored"]
