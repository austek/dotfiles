import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "bin"))
sys.path.insert(0, str(_ROOT / "local" / ".local" / "bin"))


@pytest.fixture(autouse=True)
def no_network_tool_fetch(monkeypatch):
    def refuse(url):
        raise AssertionError(f"test attempted a real download: {url}")

    monkeypatch.setattr("dotfiles_setup.tools.fetch_https", refuse)
