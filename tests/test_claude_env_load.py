import json
import shutil
import subprocess
from pathlib import Path

import pytest

LOADER = Path(__file__).parent.parent / "bin" / "claude-env-load"


def _run(tmp_path, args, secrets=None, mode=0o600, preset=None, extra=None, loader=LOADER):
    home = tmp_path / "home"
    (home / ".config/dotfiles").mkdir(parents=True)
    if secrets is not None:
        path = home / ".config/dotfiles/secrets.env"
        path.write_text(secrets)
        path.chmod(mode)
    if preset is not None:
        (home / ".config/dotfiles/state.json").write_text(json.dumps({"preset_name": preset}))
    return subprocess.run(
        [str(loader), *args],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", **(extra or {})},
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )


def test_exports_secrets_to_the_command(tmp_path):
    result = _run(tmp_path, ["sh", "-c", 'echo "$FOO"'], secrets="FOO='bar baz'\n")
    assert result.stdout.strip() == "bar baz"


def test_secrets_named_like_parser_state_keep_their_values(tmp_path):
    secrets = "value=first\nkey=second\nline=third\nreason=fourth\nmode=fifth\nFOO=last\n"
    result = _run(tmp_path, ["sh", "-c", 'echo "$value|$key|$line|$reason|$mode|$FOO"'], secrets=secrets)
    assert result.stdout.strip() == "first|second|third|fourth|fifth|last"


def test_skips_and_warns_for_a_group_readable_file(tmp_path):
    result = _run(tmp_path, ["sh", "-c", 'echo "[$FOO]"'], secrets="FOO=leak\n", mode=0o644)
    assert result.stdout.strip() == "[]"
    assert "claude-env-load: secrets.env skipped: group/other can access it" in result.stderr


def test_prepends_the_newest_nvm_node_directory(tmp_path):
    for version in ("v20.1.0", "v22.3.0"):
        (tmp_path / "home/.nvm/versions/node" / version / "bin").mkdir(parents=True)
    result = _run(tmp_path, ["sh", "-c", 'echo "$PATH"'])
    assert result.stdout.startswith(str(tmp_path / "home/.nvm/versions/node/v22.3.0/bin") + ":")


def test_check_runs_nothing_and_warns(tmp_path):
    result = _run(tmp_path, ["--check"], secrets="FOO=x\n", mode=0o644)
    assert result.returncode == 0
    assert "secrets.env skipped" in result.stderr


def test_without_a_command_it_fails_with_usage(tmp_path):
    result = _run(tmp_path, [])
    assert result.returncode == 64


needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
SHOW = ["sh", "-c", 'echo "$CLAUDE_CODE_ENABLE_TELEMETRY|$OTEL_RESOURCE_ATTRIBUTES|$OTEL_EXPORTER_OTLP_ENDPOINT"']


@needs_jq
def test_exports_otel_env_for_the_account(tmp_path):
    result = _run(tmp_path, SHOW, preset="personal", extra={"CLAUDE_OTEL_ACCOUNT": "burst"})
    enabled, attrs, _ = result.stdout.strip().split("|")
    assert enabled == "1"
    assert "account=burst" in attrs.split(",")


def test_no_otel_env_without_the_variable(tmp_path):
    result = _run(tmp_path, SHOW, preset="personal")
    assert result.stdout.strip() == "||"


@needs_jq
def test_work_preset_exports_no_otel_env(tmp_path):
    result = _run(tmp_path, SHOW, preset="work", extra={"CLAUDE_OTEL_ACCOUNT": "main"})
    assert result.stdout.strip() == "||"


@needs_jq
def test_secrets_env_overrides_the_otel_endpoint(tmp_path):
    result = _run(
        tmp_path, SHOW, secrets="OTEL_EXPORTER_OTLP_ENDPOINT=http://x:1\n",
        preset="personal", extra={"CLAUDE_OTEL_ACCOUNT": "main"},
    )
    enabled, _, endpoint = result.stdout.strip().split("|")
    assert (enabled, endpoint) == ("1", "http://x:1")


@needs_jq
def test_claude_otel_endpoint_in_secrets_env_reaches_the_script(tmp_path):
    result = _run(
        tmp_path, SHOW, secrets="CLAUDE_OTEL_ENDPOINT=http://mine:9\n",
        preset="personal", extra={"CLAUDE_OTEL_ACCOUNT": "main"},
    )
    enabled, _, endpoint = result.stdout.strip().split("|")
    assert (enabled, endpoint) == ("1", "http://mine:9")


@needs_jq
def test_the_otel_account_variable_does_not_reach_the_command(tmp_path):
    result = _run(
        tmp_path, ["sh", "-c", 'echo "[${CLAUDE_OTEL_ACCOUNT-unset}]"'],
        preset="personal", extra={"CLAUDE_OTEL_ACCOUNT": "main"},
    )
    assert result.stdout.strip() == "[unset]"


def test_missing_otel_script_does_not_block_the_command(tmp_path):
    lone = tmp_path / "lone"
    lone.mkdir()
    copy = lone / "claude-env-load"
    shutil.copy(LOADER, copy)
    result = _run(tmp_path, ["sh", "-c", "echo ran"], extra={"CLAUDE_OTEL_ACCOUNT": "main"}, loader=copy)
    assert (result.returncode, result.stdout.strip()) == (0, "ran")
