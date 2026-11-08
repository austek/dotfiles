"""Properties of the Claude Code hooks that the verdict table cannot show: symlinks and fuzzed input."""
import importlib.util
import random
import subprocess
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stowed hooks package

from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "claude" / ".claude" / "hooks"
spec = importlib.util.spec_from_file_location("allow_compound_bash", HOOKS / "allow-compound-bash.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

RULES = {"allow": [hook.to_regex(p) for p in ("git *", "gh *", "find *")], "deny": [hook.to_regex("git push * main*")], "ask": []}
FUZZ_PIECES = [
    "git ", "echo ", "cat ", "ls ", "jq ", "a", "b", "main", "$", "'", '"', "{", "}", ",", "..", "@", "(", ")", "`",
    ";", "|", "&&", "<", ">", "\\", "-", "~/", "/", " ", "$(", "${", "$'", "\n",
]


def test_a_symlink_into_a_secret_directory_is_not_auto_allowed(tmp_path):
    secrets = tmp_path / ".ssh"
    secrets.mkdir()
    (secrets / "key").write_text("x")
    (tmp_path / "link").symlink_to(secrets)
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "file").write_text("x")
    assert not hook.should_allow(f"cat {tmp_path}/link/key", RULES)
    assert hook.should_allow(f"cat {tmp_path}/plain/file", RULES)


@pytest.mark.parametrize("seed", range(4))
def test_whatever_is_auto_allowed_is_valid_bash(seed):
    generator = random.Random(seed)
    commands = ["".join(generator.choices(FUZZ_PIECES, k=generator.randint(1, 9))) for _ in range(400)]
    allowed = [command for command in commands if hook.should_allow(command, RULES)]
    assert allowed, "the fuzz inputs never produced an allowed command, so the check below proves nothing"
    for command in allowed:
        parsed = subprocess.run(["bash", "-n", "-c", command], capture_output=True, check=False)
        assert parsed.returncode == 0, command


@pytest.mark.parametrize("command", ["git push origin $'main'", "git log {a,b}", "git status ${x@P}"])
def test_expansions_the_tokenizer_does_not_model_are_never_allowed(command):
    assert not hook.should_allow(command, RULES)
