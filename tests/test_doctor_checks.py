import json
import os
import shlex
import subprocess
from pathlib import Path

from dotfiles_setup import doctor_checks, release_installers
from dotfiles_setup.doctor_checks import (
    CHECKS,
    CheckContext,
    check_plugin_load_errors,
    check_stale_copies,
)
from dotfiles_setup.log import Logger
from dotfiles_setup.tooling import Tooling


def _ctx(run, packages=()):
    return CheckContext(Tooling(Logger(dry_run=False), Path("/home/nobody"), run=run), packages)


def _run_returning(plugins):
    return lambda argv, **_: subprocess.CompletedProcess(argv, 0, stdout=json.dumps(plugins), stderr="")


def _run_exit(code, stderr=""):
    return lambda argv, **_: subprocess.CompletedProcess(argv, code, stdout="", stderr=stderr)


def test_plugin_with_errors_becomes_a_fixable_finding():
    plugins = [{"id": "b@m", "scope": "user", "errors": ["Path not found: /c (skills)"]}]
    (f,) = check_plugin_load_errors(_ctx(_run_returning(plugins))).findings
    assert f.check == "plugin_load_errors"
    assert "b@m has load errors: Path not found: /c (skills)" in f.text
    assert f.affects == ("b@m",)
    assert f.commands == (
        ("claude", "plugin", "uninstall", "b@m", "--keep-data", "--scope", "user"),
        ("claude", "plugin", "install", "b@m", "--scope", "user"),
    )


def test_a_non_user_scope_plugin_is_manual_and_names_its_project():
    plugins = [
        {"id": "b@m", "scope": "user", "errors": ["x"]},
        {"id": "b@m", "scope": "project", "projectPath": "/work/app", "errors": ["x"]},
    ]
    user, project = check_plugin_load_errors(_ctx(_run_returning(plugins))).findings
    assert user.fixable
    assert not project.fixable
    assert "/work/app" in project.text
    assert "In /work/app: claude plugin uninstall b@m --keep-data --scope project" in project.advice
    assert "claude plugin install b@m --scope project" in project.advice


def test_the_same_plugin_local_to_two_projects_gives_two_distinct_findings():
    plugins = [
        {"id": "b@m", "scope": "local", "projectPath": p, "errors": ["x"]} for p in ("/work/a", "/work/b")
    ]
    first, second = check_plugin_load_errors(_ctx(_run_returning(plugins))).findings
    assert first.text != second.text
    assert first.affects != second.affects


def test_a_non_user_plugin_without_a_project_path_still_gets_advice():
    plugins = [{"id": "b@m", "scope": "local", "errors": ["x"]}]
    (f,) = check_plugin_load_errors(_ctx(_run_returning(plugins))).findings
    assert not f.fixable
    assert "the project that owns it" in f.advice


def test_healthy_plugins_give_no_findings():
    plugins = [{"id": "a@m", "scope": "user"}, {"id": "c@m", "scope": "user", "errors": []}]
    assert check_plugin_load_errors(_ctx(_run_returning(plugins))).findings == ()


def test_missing_claude_is_skipped_not_a_finding():
    out = check_plugin_load_errors(_ctx(_run_exit(127)))
    assert out.findings == ()
    assert "not installed" in out.skipped


def test_failing_claude_list_is_a_finding_with_advice():
    (f,) = check_plugin_load_errors(_ctx(_run_exit(1, stderr="boom"))).findings
    assert "boom" in f.text
    assert f.advice
    assert not f.fixable


def test_unparsable_claude_output_is_a_finding_with_advice():
    def run(argv, **_):
        return subprocess.CompletedProcess(argv, 0, stdout="not json", stderr="")

    (f,) = check_plugin_load_errors(_ctx(run)).findings
    assert f.advice
    assert not f.fixable


def _shadow_ctx(tmp_path, monkeypatch, packages=("sops",)):
    system = tmp_path / "usr-local-bin"
    system.mkdir()
    monkeypatch.setattr(release_installers, "SYSTEM_BIN_DIR", system)
    for directory in (tmp_path / ".local/bin", tmp_path / "bin"):
        directory.mkdir(parents=True)
        (directory / "sops").write_text("x")
        (directory / "sops").chmod(0o755)
    run = _run_exit(0)
    return CheckContext(Tooling(Logger(dry_run=False), tmp_path, run=run), packages)


def test_shadowing_copy_is_a_manual_finding_naming_the_rm_path(tmp_path, monkeypatch):
    (f,) = check_stale_copies(_shadow_ctx(tmp_path, monkeypatch)).findings
    copy = tmp_path / "bin" / "sops"
    assert f.check == "stale_copies"
    assert f"{copy} precedes {tmp_path / '.local/bin/sops'} on PATH and shadows it" in f.text
    assert f.advice == f"rm {copy}"
    assert not f.fixable


def test_advice_quotes_a_path_with_spaces(tmp_path, monkeypatch):
    home = tmp_path / "my home"
    home.mkdir()
    (f,) = check_stale_copies(_shadow_ctx(home, monkeypatch)).findings
    assert f.advice == f"rm {shlex.quote(str(home / 'bin' / 'sops'))}"
    assert f.advice.startswith("rm '")


def test_copy_in_a_directory_the_user_cannot_write_says_it_needs_root(tmp_path, monkeypatch):
    ctx = _shadow_ctx(tmp_path, monkeypatch)
    real_access = os.access
    monkeypatch.setattr(doctor_checks.os, "access", lambda p, mode, **kw: mode != os.W_OK and real_access(p, mode, **kw))
    copy = tmp_path / "bin" / "sops"
    assert check_stale_copies(ctx).findings[0].advice == f"rm {copy} (as root: {copy.parent} is not writable)"


def test_shadowed_by_and_off_path_cases_are_not_findings(tmp_path, monkeypatch):
    ctx = _shadow_ctx(tmp_path, monkeypatch)
    (tmp_path / "bin" / "sops").unlink()
    (release_installers.SYSTEM_BIN_DIR / "sops").write_text("old")
    assert check_stale_copies(ctx).findings == ()


def test_no_saved_preset_skips_the_check(tmp_path, monkeypatch):
    out = check_stale_copies(_shadow_ctx(tmp_path, monkeypatch, packages=None))
    assert out.findings == ()
    assert "no saved preset" in out.skipped


def test_registry_order_and_reserved_name():
    assert list(CHECKS) == ["stale_copies", "plugin_load_errors"]
    assert "fix" not in CHECKS
