import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "zsh" / ".config" / "zsh" / "functions"

pytestmark = pytest.mark.skipif(
    shutil.which("zsh") is None or shutil.which("jq") is None, reason="zsh or jq not installed"
)


def _run(tmp_path: Path, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    full_env = {
        "PATH": f"{bin_dir}:{ROOT / 'bin'}:{os.environ['PATH']}",
        "HOME": str(home),
        "LOG": str(tmp_path / "log"),
        "DOTFILES_ROOT": str(tmp_path / "dotfiles"),
        **(env or {}),
    }
    quoted = shlex.quote(str(FUNCTIONS))
    setup = f"fpath=({quoted} $fpath); autoload -Uz {quoted}/*(:t)\n"
    return subprocess.run(
        ["zsh", "-f", "-c", setup + script], capture_output=True, text=True, env=full_env, timeout=30, check=False
    )


def _manifest(tmp_path: Path, name: str) -> dict:
    return json.loads((tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts" / f"{name}.json").read_text())


def _preset(tmp_path: Path, name: str, footholds: list[str] | None = None) -> None:
    state = tmp_path / "home" / ".config" / "dotfiles"
    state.mkdir(parents=True, exist_ok=True)
    (state / "state.json").write_text(json.dumps({"preset_name": name}))
    presets = tmp_path / "dotfiles" / "presets"
    presets.mkdir(parents=True, exist_ok=True)
    (presets / f"{name}.json").write_text(json.dumps({"footholds": footholds or []}))


def _stub_claude(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text(
        '#!/bin/sh\necho "cfg=${CLAUDE_CONFIG_DIR-unset} key=${ANTHROPIC_API_KEY-unset} '
        'res=${OTEL_RESOURCE_ATTRIBUTES-unset} on=${CLAUDE_CODE_ENABLE_TELEMETRY-unset}" >> "$LOG"\n'
    )
    stub.chmod(0o755)


def _log(tmp_path: Path) -> list[str]:
    log = tmp_path / "log"
    return log.read_text().splitlines() if log.exists() else []


def test_create_makes_the_dir_and_a_manifest(tmp_path):
    result = _run(tmp_path, "claude-account create work2")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home" / ".claude-work2").is_dir()
    assert _manifest(tmp_path, "work2") == {}
    assert "claude --account work2" in result.stdout


def test_create_stores_the_options(tmp_path):
    script = "claude-account create work2 --telemetry off --label team=data --otel-account w2 --api-key-env KEY_W2"
    assert _run(tmp_path, script).returncode == 0
    assert _manifest(tmp_path, "work2") == {
        "telemetry": False,
        "labels": {"team": "data"},
        "otel_account": "w2",
        "api_key_env": "KEY_W2",
    }


@pytest.mark.parametrize("name", ["main", "Bad", "a/b", ""])
def test_create_rejects_invalid_names(tmp_path, name):
    result = _run(tmp_path, f"claude-account create '{name}'")
    assert result.returncode == 2
    assert not list((tmp_path / "home").glob(".claude-*"))


def test_create_refuses_an_existing_account(tmp_path):
    (tmp_path / "home" / ".claude-burst").mkdir(parents=True)
    result = _run(tmp_path, "claude-account create burst")
    assert result.returncode == 1
    assert "already exists" in result.stderr


@pytest.mark.parametrize(
    "option",
    ["--telemetry maybe", "--label host=x", "--label novalue", "--api-key-env 1bad", "--bogus"],
)
def test_create_rejects_bad_options_without_creating_anything(tmp_path, option):
    result = _run(tmp_path, f"claude-account create work2 {option}")
    assert result.returncode == 2
    assert not (tmp_path / "home" / ".claude-work2").exists()
    assert not (tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts" / "work2.json").exists()


def test_update_changes_and_removes_settings(tmp_path):
    script = (
        "claude-account create work2 --label team=data --label env=dev\n"
        "claude-account update work2 --telemetry off --unset-label team --api-key-env K\n"
        "claude-account update work2 --no-api-key"
    )
    assert _run(tmp_path, script).returncode == 0
    assert _manifest(tmp_path, "work2") == {"labels": {"env": "dev"}, "telemetry": False}


def test_update_works_on_main(tmp_path):
    assert _run(tmp_path, "claude-account update main --telemetry off").returncode == 0
    assert _manifest(tmp_path, "main") == {"telemetry": False}


def test_update_needs_an_existing_account_and_an_option(tmp_path):
    assert _run(tmp_path, "claude-account update ghost --telemetry on").returncode == 1
    _run(tmp_path, "claude-account create work2")
    assert _run(tmp_path, "claude-account update work2").returncode == 2


def test_ls_lists_every_account_with_its_state(tmp_path):
    claude = tmp_path / "home" / ".claude"
    claude.mkdir(parents=True)
    (claude / ".credentials.json").write_text("{}")
    _run(tmp_path, "claude-account create work2 --telemetry off --api-key-env K2")
    result = _run(tmp_path, "claude-account ls")
    rows = {line.split()[0]: line.split() for line in result.stdout.splitlines()[1:]}
    assert rows["main"][:3] == ["main", "yes", "on"]
    assert rows["work2"] == ["work2", "no", "off", "-", "K2"]


def test_unknown_subcommand_prints_usage(tmp_path):
    result = _run(tmp_path, "claude-account nope")
    assert (result.returncode, "Usage:" in result.stderr) == (2, True)


def test_rename_moves_the_account_and_keeps_the_dashboard_label(tmp_path):
    _run(tmp_path, "claude-account create old --label team=data")
    result = _run(tmp_path, "claude-account rename old new")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "home" / ".claude-old").exists()
    assert (tmp_path / "home" / ".claude-new").is_dir()
    assert _manifest(tmp_path, "new") == {"labels": {"team": "data"}, "otel_account": "old"}


def test_rename_keeps_an_existing_label_override(tmp_path):
    _run(tmp_path, "claude-account create old --otel-account dash")
    _run(tmp_path, "claude-account rename old new")
    assert _manifest(tmp_path, "new")["otel_account"] == "dash"


def test_rename_with_relabel_drops_the_override(tmp_path):
    _run(tmp_path, "claude-account create old --otel-account dash")
    _run(tmp_path, "claude-account rename old new --relabel")
    assert "otel_account" not in _manifest(tmp_path, "new")


def test_rename_moves_the_saved_with_selection(tmp_path):
    _run(tmp_path, "claude-account create old")
    state = tmp_path / "home" / ".local" / "state" / "dotfiles" / "claude-with"
    state.mkdir(parents=True)
    (state / "old").write_text("idea")
    _run(tmp_path, "claude-account rename old new")
    assert (state / "new").read_text() == "idea"
    assert not (state / "old").exists()


@pytest.mark.parametrize(("old", "new"), [("main", "x"), ("old", "main"), ("ghost", "x"), ("old", "taken")])
def test_rename_rejects_bad_targets(tmp_path, old, new):
    _run(tmp_path, "claude-account create old; claude-account create taken")
    result = _run(tmp_path, f"claude-account rename {old} {new}")
    assert result.returncode != 0
    assert (tmp_path / "home" / ".claude-old").is_dir()


def test_rename_refuses_a_foothold_account(tmp_path):
    _preset(tmp_path, "homelab", footholds=["main", "burst"])
    _run(tmp_path, "claude-account create burst")
    result = _run(tmp_path, "claude-account rename burst renamed")
    assert result.returncode == 1
    assert "foothold" in result.stderr
    assert (tmp_path / "home" / ".claude-burst").is_dir()


def test_claude_account_flag_refuses_an_account_that_was_not_created(tmp_path):
    _stub_claude(tmp_path)
    result = _run(tmp_path, "claude --account ghost")
    assert (result.returncode, _log(tmp_path)) == (1, [])
    assert "claude-account create ghost" in result.stderr


def test_telemetry_off_sends_nothing_and_labels_are_added(tmp_path):
    _stub_claude(tmp_path)
    _preset(tmp_path, "homelab")
    _run(tmp_path, "claude-account create quiet --telemetry off; claude-account create loud --label team=data --otel-account dash")
    _run(tmp_path, "claude --account quiet; claude --account loud")
    quiet, loud = _log(tmp_path)
    assert "res=unset on=unset" in quiet
    assert "on=1" in loud
    assert "res=account=dash,host=homelab,machine=" in loud
    assert ",team=data" in loud


def test_main_telemetry_can_be_turned_off(tmp_path):
    _stub_claude(tmp_path)
    _preset(tmp_path, "homelab")
    _run(tmp_path, "claude-account update main --telemetry off")
    _run(tmp_path, "claude")
    assert "on=unset" in _log(tmp_path)[0]


def test_api_key_account_exports_the_key_from_its_variable(tmp_path):
    _stub_claude(tmp_path)
    _run(tmp_path, "claude-account create keyed --api-key-env KEY_VAR")
    result = _run(tmp_path, "claude --account keyed", env={"KEY_VAR": "sk-test-123"})
    assert result.returncode == 0, result.stderr
    assert "key=sk-test-123" in _log(tmp_path)[0]


def test_api_key_account_fails_when_its_variable_is_unset(tmp_path):
    _stub_claude(tmp_path)
    _run(tmp_path, "claude-account create keyed --api-key-env KEY_VAR")
    result = _run(tmp_path, "claude --account keyed")
    assert (result.returncode, _log(tmp_path)) == (1, [])
    assert "$KEY_VAR is not set" in result.stderr


def test_the_api_key_does_not_leak_into_the_calling_shell(tmp_path):
    _stub_claude(tmp_path)
    _run(tmp_path, "claude-account create keyed --api-key-env KEY_VAR")
    result = _run(tmp_path, "claude --account keyed; print -r -- ${ANTHROPIC_API_KEY-unset}", env={"KEY_VAR": "sk-1"})
    assert result.stdout.strip() == "unset"


def _write_manifest(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_corrupt_manifest_stops_the_launch(tmp_path):
    _stub_claude(tmp_path)
    _preset(tmp_path, "homelab")
    _run(tmp_path, "claude-account create work2")
    _write_manifest(tmp_path, "work2", '{"telemetry": false,}')
    result = _run(tmp_path, "claude --account work2")
    assert (result.returncode, _log(tmp_path)) == (1, [])
    assert "not valid JSON" in result.stderr


def test_a_corrupt_manifest_sends_no_telemetry(tmp_path):
    _preset(tmp_path, "homelab")
    _write_manifest(tmp_path, "work2", '{"telemetry": false,}')
    assert _run(tmp_path, "claude-otel-env work2").stdout == ""


def test_hand_edited_labels_are_sanitised_in_the_telemetry_env(tmp_path):
    _preset(tmp_path, "homelab")
    _write_manifest(tmp_path, "w", '{"otel_account": "a b,c=d", "labels": {"k k": "v,v=1"}}')
    env = _run(tmp_path, "claude-otel-env w").stdout
    (resources,) = [line for line in env.splitlines() if line.startswith("OTEL_RESOURCE_ATTRIBUTES=")]
    attrs = resources.split("=", 1)[1].split(",")
    assert attrs[0] == "account=a_b_c_d"
    assert attrs[-1] == "k_k=v_v_1"
    assert len(attrs) == 5


def test_a_failed_update_leaves_no_temp_files(tmp_path):
    _run(tmp_path, "claude-account create work2")
    manifest = _write_manifest(tmp_path, "work2", "not json")
    result = _run(tmp_path, "claude-account update work2 --telemetry off")
    assert result.returncode != 0
    assert sorted(p.name for p in manifest.parent.iterdir()) == ["work2.json"]


def test_create_removes_the_manifest_when_linking_fails(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    link = bin_dir / "claude-account-link"
    link.write_text("#!/bin/sh\nexit 1\n")
    link.chmod(0o755)
    result = _run(tmp_path, "claude-account create work2 --telemetry off")
    assert result.returncode == 1
    assert not (tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts" / "work2.json").exists()


def _tmux_sessions(tmp_path: Path, sessions: list[str] | dict[str, str | None]) -> None:
    recorded = sessions if isinstance(sessions, dict) else dict.fromkeys(sessions)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "tmux"
    listing = "".join(f"echo {shlex.quote(name)}\n" for name in recorded)
    cases = "".join(
        f"    ={shlex.quote(name)}) echo DOTFILES_CLAUDE_ACCOUNT={shlex.quote(account)} ;;\n"
        for name, account in recorded.items()
        if account is not None
    )
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = show-environment ]; then\n'
        '  case "$3" in\n'
        f"{cases}"
        "    *) exit 1 ;;\n"
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        f"{listing}"
    )
    stub.chmod(0o755)


def test_rename_matches_the_recorded_account_not_a_name_prefix(tmp_path):
    _run(tmp_path, "claude-account create team")
    _tmux_sessions(tmp_path, {"claude-team-dev-proj-123": "team-dev"})
    assert _run(tmp_path, "claude-account rename team renamed").returncode == 0


def test_rename_refuses_when_the_recorded_account_matches(tmp_path):
    _run(tmp_path, "claude-account create team")
    _tmux_sessions(tmp_path, {"claude-team-dev-proj-123": "team"})
    assert _run(tmp_path, "claude-account rename team renamed").returncode == 1


@pytest.mark.parametrize("args", ["--account=", "--account ''"])
def test_an_empty_account_name_is_rejected(tmp_path, args):
    script = f"local -a accounts=() with_names=() rest=(); _claude_parse_args {args}"
    result = _run(tmp_path, f"f() {{ {script} }}; f")
    assert result.returncode == 2
    assert "needs a name" in result.stderr


def test_a_failed_manifest_write_after_the_move_restores_the_old_name(tmp_path):
    _run(tmp_path, "claude-account create old")
    manifests = tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts"
    (manifests / "old.json").unlink()
    manifests.chmod(0o555)
    try:
        result = _run(tmp_path, "claude-account rename old new")
    finally:
        manifests.chmod(0o755)
    assert result.returncode == 1
    assert (tmp_path / "home" / ".claude-old").is_dir()
    assert not (tmp_path / "home" / ".claude-new").exists()


def test_update_rejects_a_path_alias_as_the_account_name(tmp_path):
    _run(tmp_path, "claude-account create team")
    _run(tmp_path, "claude-account create other")
    result = _run(tmp_path, "claude-account update team/../other --label k=v")
    assert result.returncode == 2
    assert "invalid name" in result.stderr


def test_a_failed_link_leaves_no_account_directory(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "claude-account-link"
    stub.write_text('#!/bin/sh\nmkdir -p "$HOME/.claude-$1"\nexit 1\n')
    stub.chmod(0o755)
    assert _run(tmp_path, "claude-account create broken").returncode == 1
    assert not (tmp_path / "home" / ".claude-broken").exists()


def test_rename_refuses_an_account_with_a_running_tmux_session(tmp_path):
    _run(tmp_path, "claude-account create old")
    _tmux_sessions(tmp_path, ["claude-old-proj-123", "claude-other-proj-9"])
    result = _run(tmp_path, "claude-account rename old new")
    assert result.returncode == 1
    assert "running tmux session" in result.stderr
    assert (tmp_path / "home" / ".claude-old").is_dir()
    assert not (tmp_path / "home" / ".claude-new").exists()


def test_rename_refuses_an_account_running_with_mcp_entries(tmp_path):
    _run(tmp_path, "claude-account create old")
    _tmux_sessions(tmp_path, ["claude-old-with-idea-77-proj-123"])
    assert _run(tmp_path, "claude-account rename old new").returncode == 1


def test_rename_ignores_sessions_of_other_accounts(tmp_path):
    _run(tmp_path, "claude-account create old")
    _tmux_sessions(tmp_path, ["claude-main-proj-123", "claude-burst-proj-9"])
    assert _run(tmp_path, "claude-account rename old new").returncode == 0


def test_a_failed_manifest_move_undoes_the_rename(tmp_path):
    _run(tmp_path, "claude-account create old --api-key-env KEEP_ME")
    manifests = tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts"
    manifests.chmod(0o555)
    try:
        result = _run(tmp_path, "claude-account rename old new")
    finally:
        manifests.chmod(0o755)
    assert result.returncode == 1
    assert (tmp_path / "home" / ".claude-old").is_dir()
    assert not (tmp_path / "home" / ".claude-new").exists()
    assert json.loads((manifests / "old.json").read_text()) == {"api_key_env": "KEEP_ME"}


def test_a_rejected_rename_leaves_the_target_untouched(tmp_path):
    _run(tmp_path, "claude-account create old; claude-account create taken --label team=x")
    result = _run(tmp_path, "claude-account rename old taken")
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert _manifest(tmp_path, "taken") == {"labels": {"team": "x"}}


def test_the_api_key_never_appears_on_a_command_line(tmp_path):
    _stub_claude(tmp_path)
    _run(tmp_path, "claude-account create keyed --api-key-env KEY_VAR")
    bin_dir = tmp_path / "bin"
    recorder = bin_dir / "env"
    recorder.write_text('#!/bin/sh\necho "env $*" >> "$LOG.env"\nexec /usr/bin/env "$@"\n')
    recorder.chmod(0o755)
    _run(tmp_path, "claude --account keyed", env={"KEY_VAR": "sk-secret-9"})
    assert "key=sk-secret-9" in _log(tmp_path)[0]
    argv_log = (tmp_path / "log.env").read_text()
    assert "CLAUDE_CONFIG_DIR" in argv_log
    assert "sk-secret-9" not in argv_log


def test_remove_deletes_the_dir_manifest_and_saved_with_names(tmp_path):
    _run(tmp_path, "claude-account create old --label team=data")
    state = tmp_path / "home" / ".local" / "state" / "dotfiles" / "claude-with"
    state.mkdir(parents=True)
    (state / "old").write_text("idea")
    result = _run(tmp_path, "claude-account remove old --yes")
    assert result.returncode == 0, result.stderr
    manifest = tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts" / "old.json"
    assert not any(p.exists() for p in (tmp_path / "home" / ".claude-old", manifest, state / "old"))


def test_remove_does_not_follow_links_into_the_main_config(tmp_path):
    keep = tmp_path / "home" / ".claude"
    keep.mkdir(parents=True)
    (keep / "settings.json").write_text("{}")
    _run(tmp_path, "claude-account create old")
    _run(tmp_path, "claude-account-link old")
    assert (tmp_path / "home" / ".claude-old" / "settings.json").is_symlink()
    _run(tmp_path, "claude-account remove old --yes")
    assert (keep / "settings.json").read_text() == "{}"


def test_remove_without_a_terminal_or_yes_keeps_the_account(tmp_path):
    _run(tmp_path, "claude-account create old")
    result = _run(tmp_path, "claude-account remove old")
    assert result.returncode == 1
    assert (tmp_path / "home" / ".claude-old").is_dir()


@pytest.mark.parametrize("name", ["main", "ghost"])
def test_remove_rejects_main_and_unknown_accounts(tmp_path, name):
    assert _run(tmp_path, f"claude-account remove {name} --yes").returncode != 0


def test_remove_refuses_a_foothold_account(tmp_path):
    _preset(tmp_path, "homelab", footholds=["main", "burst"])
    _run(tmp_path, "claude-account create burst")
    result = _run(tmp_path, "claude-account remove burst --yes")
    assert (result.returncode, (tmp_path / "home" / ".claude-burst").is_dir()) == (1, True)


def test_remove_finishes_cleanup_when_only_the_manifest_remains(tmp_path):
    _run(tmp_path, "claude-account create old")
    shutil.rmtree(tmp_path / "home" / ".claude-old")
    assert _run(tmp_path, "claude-account remove old --yes").returncode == 0
    assert not (tmp_path / "home" / ".config" / "dotfiles" / "claude-accounts" / "old.json").exists()
