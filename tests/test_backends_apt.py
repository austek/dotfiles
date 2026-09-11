from pathlib import Path

from dotfiles_setup.backends.apt import AptBackend


def test_resolve_name_returns_override_when_present():
    backend = AptBackend(dotfiles_dir=Path("/x"), backend_overrides={"bat": "batcat"})
    assert backend.resolve_name("bat") == "batcat"


def test_resolve_name_returns_logical_name_when_no_override():
    backend = AptBackend(dotfiles_dir=Path("/x"), backend_overrides={})
    assert backend.resolve_name("ripgrep") == "ripgrep"


def test_detect_true_when_apt_get_on_path(monkeypatch):
    backend = AptBackend(dotfiles_dir=Path("/x"), backend_overrides={})
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)
    assert backend.detect() is True


def test_detect_false_when_apt_get_missing(monkeypatch):
    backend = AptBackend(dotfiles_dir=Path("/x"), backend_overrides={})
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert backend.detect() is False


def test_install_invokes_setup_sh_with_expected_argv(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    package_file = tmp_path / "work.txt"
    claude_dir = tmp_path / "claude-profiles"
    result = backend.install(
        package_file, preset_name="work", claude_profile_dir=claude_dir,
        dry_run=False, run=fake_run,
    )
    assert calls == [[
        "bash", "/repo/bin/setup.sh",
        "--preset", "work",
        "--package-file", str(package_file),
        "--claude-profile-dir", str(claude_dir),
    ]]
    assert result.succeeded is True
    assert result.returncode == 0


def test_install_appends_dry_run_flag(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
        dry_run=True, run=fake_run,
    )
    assert calls[0][-1] == "--dry-run"


def test_install_omits_private_root_flag_when_not_given(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
        dry_run=False, run=fake_run,
    )
    assert "--private-root" not in calls[0]


def test_install_appends_private_root_flag_when_given(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    private_root = tmp_path / "dotfiles-private"
    backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
        dry_run=False, private_root=private_root, run=fake_run,
    )
    assert calls[0][-2:] == ["--private-root", str(private_root)]


def test_install_does_not_capture_subprocess_output(tmp_path, monkeypatch):
    """setup.sh's own step logging is the only feedback during a real install —
    capturing it would silently swallow it all until a failure (if any) prints
    it back, leaving a successful run looking hung with no live output."""
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(kwargs)

        class _Result:
            returncode = 0
            stdout = None
            stderr = None

        return _Result()

    monkeypatch.setattr("subprocess.run", recording_run)

    import subprocess as subprocess_module

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
        dry_run=False, run=subprocess_module.run,
    )
    assert calls == [{}]


def test_install_reports_failure(tmp_path):
    def fake_run(argv, **kwargs):
        class _Result:
            returncode = 1
            stdout = "apt error"
            stderr = "detail"

        return _Result()

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    result = backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
        dry_run=False, run=fake_run,
    )
    assert result.succeeded is False
    assert result.returncode == 1
    assert "apt error" in result.stdout
    assert "detail" in result.stdout
