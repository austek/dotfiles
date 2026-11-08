"""Properties of the allow hook that the verdict table cannot show: fuzzed input run under bash with stub tools."""
import os
import random
import shutil
import subprocess

import pytest
from hook_support import RULES, hook

BASH = shutil.which("bash")
ALLOWED_NAMES = hook.SAFE_COMMANDS | {"git", "gh", "find", "xargs"}
FUZZ_PIECES = [
    "git ", "echo ", "cat ", "ls ", "jq ", "find ", "a", "b", "main", "$", "'", '"', "{", "}", ",", "..", "@", "(", ")",
    "`", ";", "|", "&&", "&", "<", ">", "\\", "-", "~/", "~root", "/", " ", "$(", "${", "$'", "$HOME", "=", "*", "?", "[",
    "-delete", "-o", "\n",
]


@pytest.fixture(scope="module")
def stub_path(tmp_path_factory):
    directory = tmp_path_factory.mktemp("stubs")
    for name in ALLOWED_NAMES:
        stub = directory / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    return directory


def traced_names(command, stub_path, home):
    done = subprocess.run(
        [BASH, "--noprofile", "--norc", "-x", "-c", command], capture_output=True, text=True, timeout=5,
        env={"PATH": str(stub_path), "HOME": str(home)}, stdin=subprocess.DEVNULL, cwd=home, check=False,
    )
    names = [line.split()[1] for line in done.stderr.splitlines() if line.startswith("+ ") and len(line.split()) > 1]
    return names, done.stderr


@pytest.mark.skipif(BASH is None, reason="bash is required")
@pytest.mark.parametrize("seed", range(8))
def test_an_auto_allowed_command_only_runs_allowlisted_tools(seed, stub_path, tmp_path):
    (tmp_path / ".ssh").mkdir()
    generator = random.Random(seed)
    commands = ["".join(generator.choices(FUZZ_PIECES, k=generator.randint(1, 9))) for _ in range(500)]
    allowed = [command for command in commands if hook.should_allow(command, RULES)]
    assert allowed, "the fuzz inputs never produced an allowed command, so the check below proves nothing"
    for command in allowed:
        names, stderr = traced_names(command, stub_path, tmp_path)
        assert set(names) <= ALLOWED_NAMES | {"read", "cd"}, command
        assert "command not found" not in stderr, command
        assert list(tmp_path.iterdir()) == [tmp_path / ".ssh"], command


@pytest.mark.parametrize("command", [")", ";", "|", "git status )", "git log ${", "&& ls", "git status ||"])
def test_commands_bash_rejects_are_never_allowed(command):
    assert not hook.should_allow(command, RULES)


def test_a_symlink_into_a_secret_directory_is_not_auto_allowed(tmp_path):
    secrets = tmp_path / ".ssh"
    secrets.mkdir()
    (secrets / "key").write_text("x")
    (tmp_path / "link").symlink_to(secrets)
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "file").write_text("x")
    assert not hook.should_allow(f"cat {tmp_path}/link/key", RULES)
    assert hook.should_allow(f"cat {tmp_path}/plain/file", RULES)


@pytest.mark.parametrize("command", ["git push origin $'main'", "git log {a,b}", "git status ${x@P}"])
def test_expansions_the_tokenizer_does_not_model_are_never_allowed(command):
    assert not hook.should_allow(command, RULES)


@pytest.mark.parametrize("path", [
    "~/.config/rclone/rclone.conf", "~/.azure/accessTokens.json", "~/.pgpass", "~/.npmrc", "~/.netrc",
    "~/.git-credentials", "~/.gnupg/pubring.kbx", "~/.aws/credentials", "~/.config/dotfiles/secrets.env",
    "~/proj/.env", "~/proj/.env.local", "/proc/1/environ", "/proc/self/environ", "~/.docker/config.json",
    "~/.local/share/keyrings/login.keyring", "~/.config/gcloud/credentials.db", "/root/.ssh/id_rsa", "~root/.ssh/x",
])
def test_every_sensitive_source_blocks_auto_allow(path):
    assert not hook.should_allow(f"cat {path}", RULES)


@pytest.mark.parametrize("path", [".envrc.md", "dotenv.txt", ".dockerignore", "environment.md", "README.md"])
def test_lookalike_names_stay_allowed(path):
    assert hook.should_allow(f"cat {path}", RULES)


def test_the_stub_directory_is_the_only_path_entry(stub_path):
    assert os.listdir(stub_path)
