import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
FUNCTIONS = ROOT / "zsh" / ".config" / "zsh" / "functions"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")

FIXED = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_METRIC_EXPORT_INTERVAL": "10000",
}
DEFAULT_ENDPOINT = "http://192.168.50.2:4318"


def _home(tmp_path: Path, state: dict | None = None) -> Path:
    home = tmp_path / "home"
    (home / ".config" / "dotfiles").mkdir(parents=True)
    if state is not None:
        (home / ".config" / "dotfiles" / "state.json").write_text(json.dumps(state))
    return home


def _run(
    home: Path, script: str, cwd: Path, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = {"PATH": f"{BIN}:{os.environ['PATH']}", "HOME": str(home), **(extra or {})}
    return subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=30,
        check=False,
    )


def _otel(home: Path, cwd: Path, label: str = "main", extra: dict[str, str] | None = None) -> dict[str, str]:
    result = _run(home, f"claude-otel-env {label}", cwd, extra)
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def _attrs(values: dict[str, str]) -> dict[str, str]:
    return dict(pair.split("=", 1) for pair in values["OTEL_RESOURCE_ATTRIBUTES"].split(","))


@pytest.mark.parametrize("account", ["main", "burst", "work2"])
def test_account_name_is_the_account_label(tmp_path, account):
    home = _home(tmp_path, {"preset_name": "homelab"})
    attrs = _attrs(_otel(home, tmp_path, account))
    assert (attrs["account"], attrs["host"]) == (account, "homelab")


def test_missing_account_defaults_to_main(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    result = _run(home, "claude-otel-env", tmp_path)
    attrs = _attrs(dict(line.split("=", 1) for line in result.stdout.splitlines()))
    assert attrs["account"] == "main"


def test_fixed_values_and_default_endpoint(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    values = _otel(home, tmp_path)
    assert {k: values[k] for k in FIXED} == FIXED
    assert values["OTEL_EXPORTER_OTLP_ENDPOINT"] == DEFAULT_ENDPOINT


def test_endpoint_override_is_honoured(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    values = _otel(home, tmp_path, extra={"CLAUDE_OTEL_ENDPOINT": "http://127.0.0.1:9"})
    assert values["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:9"


def test_prompt_and_tool_detail_logging_stay_off(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    keys = _otel(home, tmp_path)
    assert not {"OTEL_LOG_USER_PROMPTS", "OTEL_LOG_TOOL_DETAILS"} & keys.keys()


def test_work_preset_prints_nothing(tmp_path):
    home = _home(tmp_path, {"preset_name": "work"})
    result = _run(home, "claude-otel-env main", tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_missing_state_file_prints_nothing(tmp_path):
    result = _run(_home(tmp_path), "claude-otel-env main", tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_missing_preset_key_prints_nothing(tmp_path):
    result = _run(_home(tmp_path, {"backend": "apt"}), "claude-otel-env main", tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_xdg_config_home_is_honoured(tmp_path):
    xdg = tmp_path / "xdg"
    (xdg / "dotfiles").mkdir(parents=True)
    (xdg / "dotfiles" / "state.json").write_text('{"preset_name": "homelab"}')
    values = _otel(_home(tmp_path), tmp_path, extra={"XDG_CONFIG_HOME": str(xdg)})
    assert _attrs(values)["host"] == "homelab"


def _project(tmp_path: Path, name: str, git: bool) -> str:
    home = _home(tmp_path, {"preset_name": "homelab"})
    cwd = tmp_path / "work" / name if name else tmp_path / "work"
    cwd.mkdir(parents=True)
    if git:
        subprocess.run(["git", "init", "-q", str(cwd)], check=True)
    return _attrs(_otel(home, cwd))["project"]


def test_project_is_git_root_basename(tmp_path):
    root = tmp_path / "repo"
    (root / "sub" / "deep").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    home = _home(tmp_path, {"preset_name": "homelab"})
    assert _attrs(_otel(home, root / "sub" / "deep"))["project"] == "repo"


def test_project_falls_back_to_pwd_basename_outside_git(tmp_path):
    assert _project(tmp_path, "plain", git=False) == "plain"


def test_project_is_sanitized(tmp_path):
    assert _project(tmp_path, "my proj,x=1", git=False) == "my_proj_x_1"


def test_sanitized_git_root_name(tmp_path):
    assert _project(tmp_path, "a b=c", git=True) == "a_b_c"


def test_project_is_unknown_for_empty_name(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    result = _run(home, "cd /; claude-otel-env main", tmp_path)
    attrs = dict(
        line.split("=", 1) for line in result.stdout.splitlines()
    )
    assert _attrs(attrs)["project"] == "unknown"


def test_machine_label_is_the_sanitised_hostname(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    attrs = _attrs(_otel(home, tmp_path, extra={"HOSTNAME": "my box:1"}))
    assert attrs["machine"] == "my_box_1"


def test_machine_falls_back_to_uname_when_hostname_is_unset(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    expected = "".join(c if c.isalnum() or c in "._-" else "_" for c in os.uname().nodename)
    assert _attrs(_otel(home, tmp_path))["machine"] == expected


def test_without_jq_prints_nothing(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("sh", "uname", "git", "basename", "tr", "cat", "dirname"):
        found = shutil.which(name)
        if found:
            (tools / name).symlink_to(found)
    env = {"PATH": str(tools), "HOME": str(home)}
    result = subprocess.run(
        ["/bin/sh", str(BIN / "claude-otel-env"), "main"],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_invalid_manifest_prints_nothing_and_stays_quiet(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    accounts = home / ".config" / "dotfiles" / "claude-accounts"
    accounts.mkdir()
    (accounts / "main.json").write_text("[1]")
    result = _run(home, "claude-otel-env main", tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_zsh_wrapper_matches_the_script(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    quoted = shlex.quote(str(FUNCTIONS))
    setup = f"fpath=({quoted} $fpath); autoload -Uz {quoted}/*(:t)\n"
    env = {"PATH": f"{BIN}:{os.environ['PATH']}", "HOME": str(home)}
    wrapped = subprocess.run(
        ["zsh", "-f", "-c", setup + "claude-otel-env main"],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False,
    )
    assert wrapped.returncode == 0
    assert wrapped.stdout == _run(home, "claude-otel-env main", tmp_path).stdout != ""


def test_label_keys_and_values_cannot_inject_delimiters(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    accounts = home / ".config" / "dotfiles" / "claude-accounts"
    accounts.mkdir()
    (accounts / "a.json").write_text(json.dumps({"labels": {"team": "a\nb", "k=k": "v", "ok": "data"}}))
    attrs = _attrs(_otel(home, tmp_path, "a"))
    assert (attrs["team"], attrs["k_k"], attrs["ok"]) == ("a_b", "v", "data")
    assert "b" not in attrs


def test_manifest_label_and_telemetry_off(tmp_path):
    home = _home(tmp_path, {"preset_name": "homelab"})
    accounts = home / ".config" / "dotfiles" / "claude-accounts"
    accounts.mkdir()
    (accounts / "a.json").write_text('{"otel_account": "x y", "labels": {"team": "t 1"}}')
    (accounts / "off.json").write_text('{"telemetry": false}')
    attrs = _attrs(_otel(home, tmp_path, "a"))
    assert (attrs["account"], attrs["team"]) == ("x_y", "t_1")
    assert _run(home, "claude-otel-env off", tmp_path).stdout == ""
