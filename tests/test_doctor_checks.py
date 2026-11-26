import json
import subprocess
from pathlib import Path

from dotfiles_setup.doctor_checks import CHECKS, CheckContext, check_plugin_load_errors
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
        ("claude", "plugin", "uninstall", "b@m", "--scope", "user"),
        ("claude", "plugin", "install", "b@m", "--scope", "user"),
    )


def test_same_plugin_in_two_scopes_gives_two_findings():
    plugins = [{"id": "b@m", "scope": s, "errors": ["x"]} for s in ("user", "project")]
    findings = check_plugin_load_errors(_ctx(_run_returning(plugins))).findings
    assert [f.commands[0][-1] for f in findings] == ["user", "project"]


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


def test_registry_order_and_reserved_name():
    assert list(CHECKS) == ["stale_copies", "plugin_load_errors"]
    assert "fix" not in CHECKS
