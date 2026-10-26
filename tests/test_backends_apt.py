import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup.backends.apt import (
    AFTER_APT_PACKAGES,
    AFTER_APT_SOURCES,
    AFTER_CLAUDE_PROFILE,
    SETUP_STEPS,
    AptBackend,
)


def test_setup_steps_match_the_steps_setup_sh_lists_in_order():
    script = Path(__file__).resolve().parent.parent / "bin" / "setup.sh"
    listed = subprocess.run(["bash", str(script), "--list-steps"], capture_output=True, text=True, check=True)
    assert listed.stdout.split() == list(SETUP_STEPS)


def test_every_hook_key_is_a_setup_step():
    assert {AFTER_APT_SOURCES, AFTER_APT_PACKAGES, AFTER_CLAUDE_PROFILE} <= set(SETUP_STEPS)


def run_with_hooks(tmp_path, hooks):
    events = []

    def fake_run(argv, **kwargs):
        events.append(argv[argv.index("--only") + 1].split(","))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    result = backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path, dry_run=False,
        step_hooks={step: (lambda name=step: events.append(f"hook:{name}") or True) for step in hooks}, run=fake_run,
    )
    return result, events


def test_each_hook_runs_right_after_the_step_it_is_keyed_on(tmp_path):
    result, events = run_with_hooks(tmp_path, [AFTER_APT_SOURCES, AFTER_APT_PACKAGES, AFTER_CLAUDE_PROFILE])
    assert result.succeeded
    assert events == [
        ["install_core_deps", "disable_snapd", "strip_snap_from_system_path", "configure_apt_sources"],
        "hook:configure_apt_sources",
        ["install_packages"],
        "hook:install_packages",
        ["enable_gpaste_extension", "install_github_bins", "configure_docker_group",
         "configure_dotfiles", "configure_claude_profile"],
        "hook:configure_claude_profile",
        ["change_shell", "set_default_terminal"],
    ]


def test_steps_not_split_by_a_hook_run_together(tmp_path):
    _, events = run_with_hooks(tmp_path, [AFTER_APT_SOURCES])
    assert [e[0] for e in events if isinstance(e, list)] == ["install_core_deps", "install_packages"]


def test_a_failed_hook_skips_the_remaining_steps(tmp_path):
    runs = []

    def fake_run(argv, **kwargs):
        runs.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    result = backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path, dry_run=False,
        step_hooks={AFTER_APT_SOURCES: lambda: True, AFTER_APT_PACKAGES: lambda: False}, run=fake_run,
    )
    assert (result.succeeded, len(runs)) == (False, 2)


def test_install_skips_the_second_segment_when_the_first_fails(tmp_path):
    runs = []

    def fake_run(argv, **kwargs):
        runs.append(argv)
        return SimpleNamespace(returncode=3, stdout="", stderr="")

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    result = backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path, dry_run=False,
        step_hooks={AFTER_APT_SOURCES: lambda: pytest.fail("tools must not run")}, run=fake_run,
    )
    assert (result.succeeded, result.returncode, len(runs)) == (False, 3, 1)


def test_install_fails_without_the_second_segment_when_a_tool_fails(tmp_path):
    runs = []

    def fake_run(argv, **kwargs):
        runs.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    result = backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path, dry_run=False,
        step_hooks={AFTER_APT_SOURCES: lambda: False}, run=fake_run,
    )
    assert (result.succeeded, len(runs)) == (False, 1)


def test_resolve_name_returns_override_when_present():
    backend = AptBackend(dotfiles_dir=Path("/x"), backend_overrides={"bat": "batcat"})
    assert backend.resolve_name("bat") == "batcat"


def test_resolve_name_returns_logical_name_when_no_override():
    backend = AptBackend(dotfiles_dir=Path("/x"), backend_overrides={})
    assert backend.resolve_name("ripgrep") == "ripgrep"


def test_apt_backend_satisfies_backend_protocol():
    from dotfiles_setup.backends import Backend

    assert isinstance(AptBackend(dotfiles_dir=Path("/x"), backend_overrides={}), Backend)


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
        "--verbosity", "0",
        "--no-banner",
        "--no-header",
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


def test_install_does_not_capture_subprocess_output(tmp_path):
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

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    backend.install(
        tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
        dry_run=False, run=recording_run,
    )
    assert calls == [{}]


def test_install_defaults_verbosity_to_zero(tmp_path):
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
    assert "--verbosity" in calls[0]
    assert calls[0][calls[0].index("--verbosity") + 1] == "0"


def test_install_forwards_verbosity(tmp_path):
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
        dry_run=False, verbosity=3, run=fake_run,
    )
    assert calls[0][calls[0].index("--verbosity") + 1] == "3"


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


def test_print_completion_asks_setup_sh_for_the_banner_only(tmp_path):
    calls = []
    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    backend.print_completion(dry_run=False, run=lambda argv, **_: calls.append(argv))
    backend.print_completion(dry_run=True, run=lambda argv, **_: calls.append(argv))
    assert calls == [
        ["bash", "/repo/bin/setup.sh", "--banner-only"],
        ["bash", "/repo/bin/setup.sh", "--banner-only", "--dry-run"],
    ]


def test_install_forwards_force_stow_only_when_requested(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    backend = AptBackend(dotfiles_dir=Path("/repo"), backend_overrides={})
    for force in (False, True):
        backend.install(
            tmp_path / "w.txt", preset_name="work", claude_profile_dir=tmp_path,
            dry_run=False, force_stow=force, run=fake_run,
        )
    assert "--force-stow" not in calls[0]
    assert "--force-stow" in calls[1]


def test_setup_argv_adds_optional_flags_in_order():
    from dotfiles_setup.backends.apt import setup_argv

    argv = setup_argv(
        Path("/r"), Path("/p.txt"), preset_name="work", claude_profile_dir=Path("/c"),
        dry_run=True, private_root=Path("/priv"), verbosity=2, force_stow=True,
    )
    assert argv[-4:] == ["--private-root", "/priv", "--force-stow", "--dry-run"]
    assert argv[:2] == ["bash", "/r/bin/setup.sh"]
