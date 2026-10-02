"""Ładuje moduły integracji bez Home Assistanta (bez wykonywania __init__.py pakietu)."""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "czynsz"

pkg = types.ModuleType("czynsz")
pkg.__path__ = [str(PKG_DIR)]
sys.modules.setdefault("czynsz", pkg)


@pytest.fixture
def tmd() -> dict:
    """Syntetyczne odpowiedzi API (struktura jak z tomojdom.pl, dane zmyślone)."""
    return json.loads((Path(__file__).parent / "fixtures" / "tmd_responses.json").read_text())
