import json
import subprocess

from dotfiles_setup.claude_plugins import update_claude_plugins
from dotfiles_setup.log import Logger

INSTALLED = [
    {"id": "a@m", "scope": "user"},
    {"id": "a@m", "scope": "project"},
    {"id": "b@m", "scope": "user"},
]


def _fake_run(responses=None, missing=False):
    calls = []

    def run(argv, **_):
        if missing:
            raise FileNotFoundError("claude")
        calls.append(tuple(argv[2:]))
        code, out = (responses or {}).get(argv[2], (0, json.dumps(INSTALLED) if argv[2] == "list" else ""))
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="boom")

    return run, calls


def test_updates_marketplaces_then_each_unique_user_plugin():
    run, calls = _fake_run()
    update_claude_plugins(Logger(dry_run=False), run=run)
    assert calls == [
        ("marketplace", "update"),
        ("list", "--json"),
        ("update", "a@m", "--scope", "user"),
        ("update", "b@m", "--scope", "user"),
    ]


def test_dry_run_runs_nothing():
    run, calls = _fake_run()
    update_claude_plugins(Logger(dry_run=True), run=run)
    assert calls == []


def test_missing_claude_is_not_fatal():
    run, _ = _fake_run(missing=True)
    update_claude_plugins(Logger(dry_run=False), run=run)


def test_marketplace_failure_still_updates_plugins():
    run, calls = _fake_run({"marketplace": (1, "")})
    update_claude_plugins(Logger(dry_run=False), run=run)
    assert ("update", "a@m", "--scope", "user") in calls


def test_plugin_update_failure_continues_with_the_rest():
    run, calls = _fake_run({"update": (1, "")})
    update_claude_plugins(Logger(dry_run=False), run=run)
    assert ("update", "b@m", "--scope", "user") in calls
