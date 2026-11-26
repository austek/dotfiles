from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import uninstallers as un
from dotfiles_setup.log import Logger
from dotfiles_setup.result import Err, Ok
from dotfiles_setup.tooling import Tooling

UV_LIST = "serena-agent v1.0\n- serena\n"


class Machine:
    def __init__(self, answers=None):
        self.commands = []
        self.envs = []
        self.answers = answers or {}

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        self.envs.append(kwargs.get("env"))
        for prefix, (code, out) in self.answers.items():
            if argv[: len(prefix)] == list(prefix):
                return SimpleNamespace(returncode=code, stdout=out, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


def make(tmp_path, machine=None, dry_run=False):
    return Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine or Machine())


def test_parse_skips_comments_blanks_and_duplicates():
    assert un.parse("# x\n\nserena\nserena\nfoo\n") == ("serena", "foo")


def test_load_appends_overlay_extras_and_treats_missing_files_as_empty(tmp_path):
    base, overlay = tmp_path / "base", tmp_path / "overlay"
    (base / "packages").mkdir(parents=True)
    (overlay / "packages").mkdir(parents=True)
    assert un.load(base, overlay) == Ok(())
    (base / un.BASE_FILE).write_text("serena\n")
    (overlay / un.EXTRAS_FILE).write_text("other\nserena\n")
    assert un.load(base, overlay) == Ok(("serena", "other"))
    assert un.load(base, None) == Ok(("serena",))


def test_load_errs_on_an_unreadable_file(tmp_path):
    (tmp_path / un.BASE_FILE).mkdir(parents=True)
    assert isinstance(un.load(tmp_path, None), Err)


@pytest.mark.parametrize("relative", ["", "/etc", "../x", "a/../b"])
def test_home_path_rejects_empty_absolute_and_parent_paths(relative):
    with pytest.raises(ValueError):
        un.HomePath(relative)


def test_uv_tool_is_present_when_uv_tool_list_names_it(tmp_path):
    t = make(tmp_path, Machine({("uv", "tool", "list"): (0, UV_LIST)}))
    assert un.is_present(t, un.UvTool("serena-agent"))
    assert not un.is_present(t, un.UvTool("serena"))
    assert not un.is_present(t, un.UvTool("serena-agent-extra"))


def test_uv_tool_is_absent_when_uv_is_missing(tmp_path):
    t = make(tmp_path, Machine({("uv",): (127, "")}))
    assert not un.is_present(t, un.UvTool("serena-agent"))


def test_mcp_is_present_when_claude_json_lists_it_without_running_claude(tmp_path):
    machine = Machine()
    t = make(tmp_path, machine)
    assert not un.is_present(t, un.ClaudeMcp("serena"))
    (tmp_path / ".claude.json").write_text("not json")
    assert not un.is_present(t, un.ClaudeMcp("serena"))
    (tmp_path / ".claude.json").write_text('{"mcpServers": {"other": {}}}')
    assert not un.is_present(t, un.ClaudeMcp("serena"))
    (tmp_path / ".claude.json").write_text('{"mcpServers": {"serena": {}}}')
    assert un.is_present(t, un.ClaudeMcp("serena"))
    assert machine.commands == []


def test_pipx_tool_is_present_when_pipx_list_names_it(tmp_path):
    t = make(tmp_path, Machine({("pipx", "list", "--short"): (0, "cozempic 1.0\nserena-agent 1.2\n")}))
    assert un.is_present(t, un.PipxTool("serena-agent"))
    assert not un.is_present(t, un.PipxTool("serena"))


def test_pipx_tool_is_absent_when_pipx_is_missing(tmp_path):
    t = make(tmp_path, Machine({("pipx",): (127, "")}))
    assert not un.is_present(t, un.PipxTool("serena-agent"))


def test_remove_uninstalls_a_pipx_install(tmp_path):
    machine = Machine({("pipx", "list", "--short"): (0, "serena-agent 1.2\n")})
    assert un.remove(make(tmp_path, machine), "serena") is True
    assert machine.ran("pipx", "uninstall", "serena-agent")


def test_a_symlinked_parent_never_redirects_a_deletion(tmp_path):
    outside = tmp_path / "outside"
    (outside / "b").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    (home / "a").symlink_to(outside)
    assert un.remove_action(make(home), un.HomePath("a/b")) is False
    assert (outside / "b").is_dir()


def test_home_path_is_present_for_a_directory_and_for_a_symlink(tmp_path):
    t = make(tmp_path)
    assert not un.is_present(t, un.HomePath(".serena"))
    (tmp_path / ".serena").mkdir()
    assert un.is_present(t, un.HomePath(".serena"))
    (tmp_path / ".serena").rmdir()
    (tmp_path / ".serena").symlink_to(tmp_path / "missing")
    assert un.is_present(t, un.HomePath(".serena"))


def test_pending_lists_only_registered_names_with_something_present(tmp_path):
    t = make(tmp_path, Machine({("uv", "tool", "list"): (0, "")}))
    assert un.pending(t, ["serena", "nope"]) == ()
    (tmp_path / ".serena").mkdir()
    assert un.pending(t, ["serena", "nope"]) == ("serena",)


def test_unknown_names_are_reported_and_never_removed(tmp_path):
    machine = Machine()
    assert un.unknown(["serena", "nope"]) == ("nope",)
    assert un.remove(make(tmp_path, machine), "nope") is False
    assert machine.commands == []


def test_remove_runs_uv_uninstall_and_mcp_remove_with_user_scope(tmp_path):
    (tmp_path / ".claude.json").write_text('{"mcpServers": {"serena": {}}}')
    machine = Machine({("uv", "tool", "list"): (0, UV_LIST)})
    assert un.remove(make(tmp_path, machine), "serena") is True
    assert machine.ran("uv", "tool", "uninstall", "serena-agent")
    assert machine.ran("claude", "mcp", "remove", "serena", "--scope", "user")


def test_remove_deletes_the_directory_tree_under_home(tmp_path):
    (tmp_path / ".serena/language_servers").mkdir(parents=True)
    (tmp_path / ".serena/language_servers/x").write_text("x")
    assert un.remove(make(tmp_path), "serena") is True
    assert not (tmp_path / ".serena").exists()


def test_mcp_removal_targets_the_main_config_even_when_an_account_dir_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/elsewhere")
    monkeypatch.setenv("UNINSTALL_TEST_MARKER", "kept")
    (tmp_path / ".claude.json").write_text('{"mcpServers": {"serena": {}}}')
    machine = Machine()
    assert un.remove_action(make(tmp_path, machine), un.ClaudeMcp("serena")) is True
    env = machine.envs[machine.commands.index(["claude", "mcp", "remove", "serena", "--scope", "user"])]
    assert "CLAUDE_CONFIG_DIR" not in env
    assert env["UNINSTALL_TEST_MARKER"] == "kept"


def test_home_path_is_present_for_a_regular_file_and_remove_deletes_it(tmp_path):
    t = make(tmp_path)
    assert not un.is_present(t, un.HomePath(".claude/cozempic-sessions.json"))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/cozempic-sessions.json").write_text("{}")
    assert un.is_present(t, un.HomePath(".claude/cozempic-sessions.json"))
    assert un.remove_action(t, un.HomePath(".claude/cozempic-sessions.json")) is True
    assert not (tmp_path / ".claude/cozempic-sessions.json").exists()
    assert (tmp_path / ".claude").is_dir()


def test_remove_cozempic_deletes_its_cli_and_data_and_nothing_else(tmp_path):
    claude = tmp_path / ".claude"
    (tmp_path / ".cozempic").mkdir()
    (tmp_path / ".cozempic/behavioral-digest.json").write_text("{}")
    (claude / "cozempic-metrics").mkdir(parents=True)
    for name in ("cozempic-sessions.json", "cozempic-sessions.json.lock", "cozempic-active-sessions.json",
                 "cozempic-active-sessions.json.lock", "settings.json", "projects.txt"):
        (claude / name).write_text("x")
    machine = Machine({("uv", "tool", "list"): (0, "cozempic v1.8.39\n- cozempic\n"), ("pipx", "list", "--short"): (0, "cozempic 1.8\n")})
    assert un.remove(make(tmp_path, machine), "cozempic") is True
    assert machine.ran("uv", "tool", "uninstall", "cozempic")
    assert machine.ran("pipx", "uninstall", "cozempic")
    assert sorted(p.name for p in claude.iterdir()) == ["projects.txt", "settings.json"]
    assert not (tmp_path / ".cozempic").exists()


def test_remove_unlinks_a_symlinked_dir_without_touching_its_target(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep").write_text("k")
    (tmp_path / ".serena").symlink_to(target)
    assert un.remove(make(tmp_path), "serena") is True
    assert not (tmp_path / ".serena").is_symlink()
    assert (target / "keep").read_text() == "k"


def test_remove_skips_absent_actions_without_running_commands(tmp_path):
    machine = Machine({("uv", "tool", "list"): (0, "")})
    assert un.remove(make(tmp_path, machine), "serena") is True
    assert not machine.ran("uv", "tool", "uninstall")
    assert not machine.ran("claude", "mcp", "remove")


def test_remove_returns_false_when_a_command_fails_and_still_tries_the_rest(tmp_path):
    (tmp_path / ".serena").mkdir()
    (tmp_path / ".claude.json").write_text('{"mcpServers": {"serena": {}}}')
    machine = Machine({("uv", "tool", "list"): (0, UV_LIST), ("uv", "tool", "uninstall"): (1, "")})
    assert un.remove(make(tmp_path, machine), "serena") is False
    assert machine.ran("claude", "mcp", "remove")
    assert not (tmp_path / ".serena").exists()


def test_the_shipped_uninstall_file_lists_only_registered_names():
    repo = Path(__file__).resolve().parent.parent
    names = un.load(repo, None).value
    assert {"serena", "cozempic"} <= set(names)
    assert un.unknown(names) == ()


def test_the_registry_covers_serena_with_all_three_actions():
    assert un.REGISTRY["serena"] == (
        un.UvTool("serena-agent"), un.PipxTool("serena-agent"), un.ClaudeMcp("serena"), un.HomePath(".serena"),
    )
