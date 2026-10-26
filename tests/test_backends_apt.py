from pathlib import Path

from dotfiles_setup.backends import Backend
from dotfiles_setup.backends.apt import AptBackend


def make(overrides=None):
    return AptBackend(dotfiles_dir=Path("/x"), backend_overrides=overrides or {})


def test_resolve_name_returns_override_when_present():
    assert make({"bat": "batcat"}).resolve_name("bat") == "batcat"


def test_resolve_name_returns_logical_name_when_no_override():
    assert make().resolve_name("ripgrep") == "ripgrep"


def test_apt_backend_satisfies_backend_protocol():
    assert isinstance(make(), Backend)


def test_detect_true_when_apt_get_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)
    assert make().detect() is True


def test_detect_false_when_apt_get_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert make().detect() is False
