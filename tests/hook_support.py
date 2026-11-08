"""Shared setup for the allow-compound-bash hook tests: the loaded module, its rules and a subprocess runner."""
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stowed hooks package

import importlib.util
import json
import subprocess
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "claude" / ".claude" / "hooks"


def load_hook(filename):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py").replace("-", "_"), HOOKS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load_hook("allow-compound-bash.py")
RULES = {
    "allow": [hook.to_regex(pattern) for pattern in ("git *", "gh *", "find *")],
    "deny": [hook.to_regex("git push * main*")],
    "ask": [],
}


def run_hook(name, payload, home, hooks=HOOKS):
    done = subprocess.run(
        [sys.executable, "-I", str(hooks / name)], input=json.dumps(payload), capture_output=True, text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, cwd=home, check=False,
    )
    return done.stdout.strip()
