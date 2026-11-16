import subprocess
from pathlib import Path

LOADER = Path(__file__).parent.parent / "bin" / "claude-env-load"


def _run(tmp_path, args, secrets=None, mode=0o600):
    home = tmp_path / "home"
    (home / ".config/dotfiles").mkdir(parents=True)
    if secrets is not None:
        path = home / ".config/dotfiles/secrets.env"
        path.write_text(secrets)
        path.chmod(mode)
    return subprocess.run(
        [str(LOADER), *args],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, cwd=tmp_path,
    )


def test_exports_secrets_to_the_command(tmp_path):
    result = _run(tmp_path, ["sh", "-c", 'echo "$FOO"'], secrets="FOO='bar baz'\n")
    assert result.stdout.strip() == "bar baz"


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
