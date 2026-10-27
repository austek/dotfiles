import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / "claude" / ".claude" / "settings.json").read_text())
HOOK_PATH = ROOT / "claude" / ".claude" / "hooks" / "allow-compound-bash.py"


def _hook():
    spec = importlib.util.spec_from_file_location("allow_compound_bash", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash_rules(kind):
    return [e[5:-1] for e in SETTINGS["permissions"].get(kind, []) if e.startswith("Bash(")]


@pytest.mark.parametrize("command", ["find", "xargs", "sed", "fd"])
def test_commands_that_run_or_write_arbitrary_files_are_not_auto_approved(command):
    assert not [r for r in _bash_rules("allow") if r.split()[0] == command]


def test_no_gh_api_rule_auto_approves_a_wildcard_endpoint():
    assert not [r for r in _bash_rules("allow") if r.startswith("gh api")]


@pytest.mark.parametrize("command", ["rg --pre ./x foo", "rg -n --pre=./x foo", "rg foo --pre ./x"])
def test_rg_with_pre_prompts_wherever_the_flag_sits(command):
    patterns = [_hook().to_regex(r) for r in _bash_rules("ask")]
    assert _hook().matches(command, patterns)


@pytest.mark.parametrize("command", ["rg foo", "rg -n 'prefix' src"])
def test_plain_rg_does_not_prompt(command):
    patterns = [_hook().to_regex(r) for r in _bash_rules("ask")]
    assert not _hook().matches(command, patterns)


def test_cozempic_auto_update_is_disabled():
    assert SETTINGS["env"]["COZEMPIC_NO_AUTO_UPDATE"] == "1"
