import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

FUNCTIONS = Path(__file__).resolve().parent.parent / "zsh" / ".config" / "zsh" / "functions"
REPO_BIN = Path(__file__).resolve().parent.parent / "bin"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def _run(tmp_path: Path, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    full_env = {
        "PATH": f"{bin_dir}:{REPO_BIN}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "LOG": str(tmp_path / "log"),
        **(env or {}),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    setup = f"fpath=({FUNCTIONS} $fpath); autoload -Uz {FUNCTIONS}/*(:t)\n"
    return subprocess.run(
        ["zsh", "-f", "-c", setup + script], capture_output=True, text=True, env=full_env, timeout=30, check=False
    )


def _log(tmp_path: Path) -> list[str]:
    log = tmp_path / "log"
    return log.read_text().splitlines() if log.exists() else []


def _claude_stub(tmp_path: Path, extra: str = "") -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "claude", f'echo "claude $*" >> "$LOG"\n{extra}')


def test_claude_with_enables_then_reverts_on_normal_exit(tmp_path):
    _claude_stub(tmp_path)
    result = _run(tmp_path, "_claude_with idea -- --resume")
    assert result.returncode == 0
    lines = _log(tmp_path)
    assert lines[0].startswith("claude mcp add --transport http idea")
    assert lines[1] == "claude --resume"
    assert lines[2] == "claude mcp remove idea -s local"


def test_claude_with_reverts_when_shell_receives_sigterm(tmp_path):
    _claude_stub(tmp_path, 'case "$1" in mcp) ;; *) kill -TERM $PPID; sleep 0.3 ;; esac')
    result = _run(tmp_path, "_claude_with idea")
    assert "claude mcp remove idea -s local" in _log(tmp_path)
    assert result.returncode == 143


def test_claude_with_skips_entry_when_secret_missing(tmp_path):
    _claude_stub(tmp_path)
    result = _run(tmp_path, "_claude_with coralogix", env={"CORALOGIX_API_KEY": ""})
    assert result.returncode == 1
    assert "$CORALOGIX_API_KEY is not set" in result.stderr
    assert _log(tmp_path) == []


def test_claude_with_rejects_unknown_name(tmp_path):
    _claude_stub(tmp_path)
    result = _run(tmp_path, "_claude_with nope")
    assert result.returncode == 1
    assert "no restore entry for 'nope'" in result.stderr


def test_claude_tmux_runs_command_directly_inside_tmux(tmp_path):
    result = _run(tmp_path, "_claude_tmux label print -r -- hello", env={"TMUX": "/tmp/x,1,0"})
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_claude_tmux_runs_command_directly_without_tty(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "tmux", 'echo tmux >> "$LOG"')
    result = _run(tmp_path, "_claude_tmux label print -r -- hello")
    assert result.stdout.strip() == "hello"
    assert _log(tmp_path) == []


def _claude_home(tmp_path: Path) -> Path:
    claude = tmp_path / "home" / ".claude"
    (claude / "projects").mkdir(parents=True)
    for name in ("settings.json", ".credentials.json", ".hidden"):
        (claude / name).write_text(name)
    (claude / "backups").mkdir()
    return claude


def test_claude_burst_runs_claude_with_its_own_config_dir(tmp_path):
    _claude_stub(tmp_path, 'echo "cfg $CLAUDE_CONFIG_DIR" >> "$LOG"')
    _claude_home(tmp_path)
    (tmp_path / "home" / ".claude-burst").mkdir()
    result = _run(tmp_path, "claude --burst --resume abc")
    assert result.returncode == 0
    assert _log(tmp_path) == ["claude --resume abc", f"cfg {tmp_path / 'home' / '.claude-burst'}"]


def _two_accounts(tmp_path: Path) -> tuple[Path, Path]:
    """A claude stub that logs the account it ran as and saves a session where that account keeps them."""
    _stub(tmp_path / "bin", "claude", (
        'cfg=${CLAUDE_CONFIG_DIR:-$HOME/.claude}\n'
        'echo "$(cat "$cfg/.credentials.json") $1" >> "$LOG"\n'
        'mkdir -p "$cfg/projects/demo" && echo "$1" > "$cfg/projects/demo/$1.jsonl"'
    ))
    main = _claude_home(tmp_path)
    (main / ".credentials.json").write_text("main-login")
    burst = tmp_path / "home" / ".claude-burst"
    burst.mkdir()
    (burst / ".credentials.json").write_text("burst-login")
    return main, burst


def test_main_and_burst_accounts_each_use_their_own_login_in_one_shell(tmp_path):
    (tmp_path / "bin").mkdir()
    _two_accounts(tmp_path)
    script = "claude one; claude --burst two; claude three; print -r -- ${CLAUDE_CONFIG_DIR-unset}"
    result = _run(tmp_path, script)
    assert result.returncode == 0
    assert _log(tmp_path) == ["main-login one", "burst-login two", "main-login three"]
    assert result.stdout.strip() == "unset"


def test_sessions_from_either_account_are_visible_to_the_other(tmp_path):
    (tmp_path / "bin").mkdir()
    main, burst = _two_accounts(tmp_path)
    _run(tmp_path, "claude from-main; claude --burst from-burst")
    expected = ["from-burst.jsonl", "from-main.jsonl"]
    assert sorted(p.name for p in (main / "projects/demo").iterdir()) == expected
    assert sorted(p.name for p in (burst / "projects/demo").iterdir()) == expected


def test_a_burst_launch_leaves_the_main_account_untouched(tmp_path):
    (tmp_path / "bin").mkdir()
    main, _ = _two_accounts(tmp_path)
    before ={p.name: p.read_text() for p in main.iterdir() if p.is_file()}
    _run(tmp_path, "claude --burst")
    assert {p.name: p.read_text() for p in main.iterdir() if p.is_file()} == before
    assert not (main / ".claude.json").exists()


def test_settings_changed_by_an_install_reach_the_burst_account(tmp_path):
    _claude_stub(tmp_path)
    main = _claude_home(tmp_path)
    (tmp_path / "home" / ".claude-burst").mkdir()
    _run(tmp_path, "claude --burst")
    (main / "settings.json").write_text("regenerated")
    assert (tmp_path / "home/.claude-burst/settings.json").read_text() == "regenerated"


def _env_stub(tmp_path: Path) -> None:
    _claude_stub(
        tmp_path,
        'echo "cfg=${CLAUDE_CONFIG_DIR-unset} otel=${CLAUDE_CODE_ENABLE_TELEMETRY-unset} res=${OTEL_RESOURCE_ATTRIBUTES-unset}" >> "$LOG"',
    )


def _account_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "home" / f".claude-{name}"
    path.mkdir(parents=True)
    return path


def _preset(tmp_path: Path, name: str) -> None:
    state = tmp_path / "home" / ".config" / "dotfiles"
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"preset_name": name}))


def test_claude_without_flags_runs_the_main_account(tmp_path):
    _env_stub(tmp_path)
    result = _run(tmp_path, "claude -p hi")
    assert result.returncode == 0
    assert _log(tmp_path) == ["claude -p hi", "cfg=unset otel=unset res=unset"]


def test_an_explicit_main_account_ignores_an_inherited_config_dir(tmp_path):
    _env_stub(tmp_path)
    _run(tmp_path, "claude --account main -p hi", env={"CLAUDE_CONFIG_DIR": "/elsewhere"})
    assert _log(tmp_path)[1] == "cfg=unset otel=unset res=unset"


def test_no_account_flag_keeps_an_inherited_config_dir(tmp_path):
    _env_stub(tmp_path)
    _run(tmp_path, "claude -p hi", env={"CLAUDE_CONFIG_DIR": "/chrome"})
    assert _log(tmp_path)[1] == "cfg=/chrome otel=unset res=unset"


@pytest.mark.parametrize("flags", ["--account work2", "--account=work2"])
def test_claude_account_flag_selects_that_accounts_config_dir(tmp_path, flags):
    _env_stub(tmp_path)
    _claude_home(tmp_path)
    work2 = _account_dir(tmp_path, "work2")
    _run(tmp_path, f"claude {flags} hi")
    assert _log(tmp_path) == ["claude hi", f"cfg={work2} otel=unset res=unset"]


def test_claude_burst_flag_is_the_burst_account(tmp_path):
    _env_stub(tmp_path)
    _claude_home(tmp_path)
    burst = _account_dir(tmp_path, "burst")
    _run(tmp_path, "claude --burst")
    assert _log(tmp_path)[1].startswith(f"cfg={burst} ")


def test_claude_rejects_conflicting_accounts(tmp_path):
    _env_stub(tmp_path)
    result = _run(tmp_path, "claude --account other --burst")
    assert (result.returncode, _log(tmp_path)) == (2, [])
    assert "conflicting accounts" in result.stderr


@pytest.mark.parametrize("name", ["Bad", "a/b", "-x"])
def test_claude_rejects_invalid_account_names(tmp_path, name):
    _env_stub(tmp_path)
    result = _run(tmp_path, f"claude --account {name}")
    assert (result.returncode, _log(tmp_path)) == (2, [])
    assert "invalid account" in result.stderr


def test_claude_does_not_create_an_account_without_a_terminal(tmp_path):
    _env_stub(tmp_path)
    result = _run(tmp_path, "claude --account fresh")
    assert (result.returncode, _log(tmp_path)) == (1, [])
    assert "does not exist" in result.stderr
    assert not (tmp_path / "home" / ".claude-fresh").exists()


def test_claude_passes_everything_after_a_double_dash_untouched(tmp_path):
    _env_stub(tmp_path)
    _claude_home(tmp_path)
    _account_dir(tmp_path, "burst")
    _run(tmp_path, "claude --burst -- --burst --with x")
    assert _log(tmp_path)[0] == "claude -- --burst --with x"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.parametrize(("flags", "account"), [("", "main"), ("--account work2", "work2"), ("--burst", "burst")])
def test_claude_labels_telemetry_with_the_account(tmp_path, flags, account):
    _env_stub(tmp_path)
    _claude_home(tmp_path)
    _preset(tmp_path, "homelab")
    for extra in {"work2", "burst"} & {account}:
        _account_dir(tmp_path, extra)
    _run(tmp_path, f"claude {flags}")
    assert f"otel=1 res=account={account},host=homelab,project=" in _log(tmp_path)[1]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_claude_sends_no_telemetry_on_the_work_preset(tmp_path):
    _env_stub(tmp_path)
    _preset(tmp_path, "work")
    _run(tmp_path, "claude")
    assert _log(tmp_path)[1] == "cfg=unset otel=unset res=unset"


def _adds(tmp_path: Path) -> list[str]:
    names = {"idea": " idea ", "sonarqube": " sonarqube "}
    adds = [line for line in _log(tmp_path) if line.startswith("claude mcp add")]
    return [name for add in adds for name, token in names.items() if token in add]


def test_claude_with_saves_the_selection_and_a_bare_with_reuses_it(tmp_path):
    _claude_stub(tmp_path)
    _run(tmp_path, "claude --with idea,sonarqube")
    assert _adds(tmp_path) == ["idea", "sonarqube"]
    (tmp_path / "log").unlink()
    result = _run(tmp_path, "claude --with -p hi")
    assert result.returncode == 0
    assert _adds(tmp_path) == ["idea", "sonarqube"]
    assert "claude -p hi" in _log(tmp_path)


def _saved_with(tmp_path: Path, account: str = "main") -> str:
    return (tmp_path / "home" / ".local" / "state" / "dotfiles" / "claude-with" / account).read_text().strip()


def test_an_unknown_with_name_does_not_overwrite_the_saved_selection(tmp_path):
    _claude_stub(tmp_path)
    _run(tmp_path, "claude --with idea")
    result = _run(tmp_path, "claude --with hello")
    assert result.returncode == 1
    assert _saved_with(tmp_path) == "idea"


def test_only_known_with_names_are_saved(tmp_path):
    _claude_stub(tmp_path)
    _run(tmp_path, "claude --with idea,nope,sonarqube")
    assert _saved_with(tmp_path) == "idea sonarqube"


def test_a_bare_with_fails_when_the_account_has_no_saved_selection(tmp_path):
    _claude_stub(tmp_path)
    _claude_home(tmp_path)
    _account_dir(tmp_path, "burst")
    _run(tmp_path, "claude --with idea")
    (tmp_path / "log").unlink()
    result = _run(tmp_path, "claude --burst --with")
    assert (result.returncode, _log(tmp_path)) == (1, [])
    assert "no saved --with selection for account 'burst'" in result.stderr


def test_with_names_lists_builtin_and_extension_entries(tmp_path):
    ext = tmp_path / "home" / ".config" / "zsh" / "claude-with.d"
    ext.mkdir(parents=True)
    (ext / "private.zsh").write_text("local -a restore_argv_my_tool=(claude mcp add my-tool)\n")
    names = _run(tmp_path, "_claude_with_names").stdout.split()
    assert {"idea", "sonarqube", "grafana", "coralogix", "my-tool"} <= set(names)
    assert len(names) == len(set(names))


def test_with_names_include_entries_an_extension_builds_dynamically(tmp_path):
    ext = tmp_path / "home" / ".config" / "zsh" / "claude-with.d"
    ext.mkdir(parents=True)
    (ext / "dynamic.zsh").write_text(
        'print -r -- "extension warning" >&2\n'
        "for _n in alpha beta-two; do\n"
        '  set -A "restore_argv_chip_${_n//-/_}" claude mcp add "chip-$_n"\n'
        "done\n"
    )
    result = _run(tmp_path, "_claude_with_names")
    assert {"chip-alpha", "chip-beta-two"} <= set(result.stdout.split())
    assert "extension warning" not in result.stderr


def test_claude_with_runs_every_claude_call_on_the_chosen_account(tmp_path):
    _env_stub(tmp_path)
    _claude_home(tmp_path)
    burst = _account_dir(tmp_path, "burst")
    result = _run(tmp_path, "claude --burst --with idea")
    assert result.returncode == 0
    cfgs = [line for line in _log(tmp_path) if line.startswith("cfg=")]
    assert len(cfgs) == 3
    assert all(line.startswith(f"cfg={burst} ") for line in cfgs)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_secrets_hydrate_writes_private_key_verbatim_with_mode_600(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "bw", 'case "$1" in status) echo \'{"status":"unlocked"}\' ;; '
         'get) printf "%s\\n" \'{"sshKey":{"privateKey":"a\\\\tb"}}\' ;; esac')
    _stub(bin_dir, "ssh-keygen", "echo ssh-ed25519 PUB")
    _stub(bin_dir, "ssh-add", "true")
    result = _run(tmp_path, "secrets_hydrate", env={"BW_SESSION": "token"})
    key = tmp_path / "home" / ".ssh" / "id_ed25519"
    assert result.returncode == 0
    assert key.read_text() == "a\\tb\n"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_secrets_hydrate_leaves_existing_key_untouched(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "bw", 'echo \'{"status":"unlocked"}\'')
    key = tmp_path / "home" / ".ssh" / "id_ed25519"
    key.parent.mkdir(parents=True)
    key.write_text("existing")
    result = _run(tmp_path, "secrets_hydrate", env={"BW_SESSION": "token"})
    assert result.returncode == 0
    assert key.read_text() == "existing"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_secrets_hydrate_fails_when_item_has_no_key(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "bw", 'case "$1" in status) echo \'{"status":"unlocked"}\' ;; get) echo \'{}\' ;; esac')
    result = _run(tmp_path, "secrets_hydrate", env={"BW_SESSION": "token"})
    assert result.returncode == 1
    assert not (tmp_path / "home" / ".ssh" / "id_ed25519").exists()


def _secrets_block() -> str:
    text = (REPO_BIN.parent / "zsh" / ".zshrc").read_text()
    return text.split("# --- SECRET ENV VARS ---")[1].split("# --- END SECRET ENV VARS ---")[0]


def _load_secrets(tmp_path: Path, mode: int) -> subprocess.CompletedProcess:
    secrets = tmp_path / "home" / ".config" / "dotfiles" / "secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("RULE028_TOKEN=abc\n")
    secrets.chmod(mode)
    script = _secrets_block() + '\nprint -r -- "[${RULE028_TOKEN-}]"\n'
    return subprocess.run(
        ["zsh", "-f", "-c", script], capture_output=True, text=True, timeout=30, check=False,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home")},
    )


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_rule028_zsh_sources_a_private_secrets_file(tmp_path, mode):
    result = _load_secrets(tmp_path, mode)
    assert result.stdout.strip() == "[abc]"
    assert result.stderr == ""


@pytest.mark.parametrize("mode", [0o640, 0o604])
def test_rule028_zsh_skips_a_secrets_file_others_can_access(tmp_path, mode):
    result = _load_secrets(tmp_path, mode)
    assert result.stdout.strip() == "[]"
    assert "secrets.env skipped: group/other can access it" in result.stderr
