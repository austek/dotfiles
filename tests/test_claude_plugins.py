import json
import subprocess

from dotfiles_setup.claude_plugins import plan_actions, update_claude_plugins
from dotfiles_setup.log import Logger

INSTALLED = [
    {"id": "a@m", "scope": "user"},
    {"id": "a@m", "scope": "project"},
    {"id": "b@m", "scope": "user"},
]
SETTINGS = {
    "extraKnownMarketplaces": {
        "m": {"source": {"source": "github", "repo": "o/m"}},
        "n": {"source": {"source": "github", "repo": "o/n"}},
    },
    "enabledPlugins": {"a@m": True, "c@n": True, "d@n": False},
}
MUTATING = ("install", "uninstall", "update")


def _fake_run(responses=None, missing=False, installed=INSTALLED, marketplaces=({"name": "m"},)):
    calls = []

    def run(argv, **_):
        if missing:
            raise FileNotFoundError("claude")
        calls.append(tuple(argv[2:]))
        out = {
            ("list", "--json"): json.dumps(installed),
            ("marketplace", "list", "--json"): json.dumps(list(marketplaces)),
        }.get(tuple(argv[2:]), "")
        code, out = (responses or {}).get(argv[2], (0, out))
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="boom")

    return run, calls


def _labels(settings, registered, installed):
    return [a.label for a in plan_actions(settings, frozenset(registered), tuple(installed))]


def _mutations(calls):
    return [c for c in calls if c[0] in MUTATING or c[:2] in (("marketplace", "add"), ("marketplace", "remove"), ("marketplace", "update"))]


def test_plan_orders_add_refresh_install_uninstall_remove_update():
    assert _labels(SETTINGS, {"m", "claude-skills"}, ["a@m", "b@m", "x@claude-skills"]) == [
        "uninstall b@m",
        "uninstall x@claude-skills",
        "remove marketplace claude-skills",
        "add marketplace n",
        "refresh marketplaces",
        "install c@n",
        "update a@m",
    ]


def test_plan_is_idempotent_once_converged():
    assert _labels(SETTINGS, {"m", "n"}, ["a@m", "c@n"]) == [
        "refresh marketplaces",
        "update a@m",
        "update c@n",
    ]


def test_plan_removes_legacy_marketplace_before_adding_its_replacement():
    labels = _labels(SETTINGS, {"claude-skills"}, [])
    assert labels.index("remove marketplace claude-skills") < labels.index("add marketplace m")


def test_plan_leaves_unmanaged_marketplaces_and_their_plugins_alone():
    labels = _labels(SETTINGS, {"m", "n", "other"}, ["a@m", "c@n", "z@other"])
    assert labels == ["refresh marketplaces", "update a@m", "update c@n", "update z@other"]


def test_plan_prunes_nothing_when_no_plugin_is_enabled():
    assert _labels({}, {"claude-skills"}, ["b@claude-skills"]) == ["refresh marketplaces", "update b@claude-skills"]


def test_run_applies_the_plan_in_order():
    run, calls = _fake_run()
    update_claude_plugins(Logger(dry_run=False), SETTINGS, run=run)
    assert calls == [
        ("marketplace", "list", "--json"),
        ("list", "--json"),
        ("uninstall", "b@m", "--scope", "user"),
        ("marketplace", "add", "o/n"),
        ("marketplace", "update"),
        ("install", "c@n", "--scope", "user"),
        ("update", "a@m", "--scope", "user"),
    ]


def test_dry_run_lists_state_but_mutates_nothing(capsys):
    run, calls = _fake_run()
    update_claude_plugins(Logger(dry_run=True), SETTINGS, run=run)
    out = capsys.readouterr().out
    assert _mutations(calls) == []
    for line in ("Would add marketplace n.", "Would install c@n.", "Would uninstall b@m.", "Would update a@m."):
        assert line in out


def test_missing_claude_is_not_fatal():
    run, _ = _fake_run(missing=True)
    update_claude_plugins(Logger(dry_run=False), SETTINGS, run=run)


def test_unlistable_state_skips_sync():
    run, calls = _fake_run({"list": (1, ""), "marketplace": (1, "")})
    update_claude_plugins(Logger(dry_run=False), SETTINGS, run=run)
    assert _mutations(calls) == []


def test_failing_action_continues_with_the_rest():
    run, calls = _fake_run({"install": (1, "")})
    update_claude_plugins(Logger(dry_run=False), SETTINGS, run=run)
    assert ("update", "a@m", "--scope", "user") in calls


def test_every_installed_plugin_is_updated_and_progress_is_logged(capsys):
    many = [{"id": f"p{i}@m", "scope": "user"} for i in range(9)]
    settings = {**SETTINGS, "enabledPlugins": {p["id"]: True for p in many}}
    run, calls = _fake_run(installed=many)
    update_claude_plugins(Logger(dry_run=False, verbosity=1), settings, run=run)
    updated = {c[1] for c in calls if c[0] == "update" and len(c) > 1 and c[1].startswith("p")}
    assert updated == {p["id"] for p in many}
    assert "Running: update p0@m" in capsys.readouterr().out
