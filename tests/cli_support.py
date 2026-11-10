import json
from datetime import UTC, datetime
from types import SimpleNamespace

from dotfiles_setup import state
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.cli import Env
from dotfiles_setup.log import Logger
from dotfiles_setup.plan import _plan
from dotfiles_setup.presets import Preset


def stub_subprocess(monkeypatch, returncode=0, stdout="installed", stderr="", calls=None):
    calls = [] if calls is None else calls

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)
    return calls


def _plan_for(tmp_path, prior=None, applied_preset="homelab", overlay_root=None, names=("zsh", "curl"), dry_run=False):
    env = Env(
        state_dir=tmp_path / "state", dotfiles_dir=tmp_path / "dotfiles",
        clock=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    preset = Preset("homelab", "test", ("apt_common.txt",), {}, None)
    return _plan(Logger(dry_run=dry_run), env, preset, names, overlay_root, prior)


def _write_optouts(tmp_path, text, name="homelab.txt"):
    package_file = tmp_path / "state" / "packages" / name
    package_file.parent.mkdir(parents=True, exist_ok=True)
    package_file.write_text(text)
    return package_file


def _prior(preset_name, applied, overlay_root=None, optouts_migrated=False):
    return state.MachineState(
        preset_name=preset_name, backend="apt", package_file="x", applied_package_names=applied,
        overlay_root=overlay_root, created_at="t", updated_at="t", optouts_migrated=optouts_migrated,
    )


def fail_flow(monkeypatch, message="apt-get exploded"):
    result = InstallResult(False, 1, message)
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: result)


def _add_preset(dotfiles_dir, name):
    (dotfiles_dir / "presets" / f"{name}.json").write_text(json.dumps({
        "description": "test",
        "package_files": ["apt_common.txt"],
        "backend_overrides": {},
        "claude_settings": f"claude_{name}.json",
    }))
    (dotfiles_dir / "claude-profiles" / f"claude_{name}.json").write_text(json.dumps({"enabledPlugins": {}}))


def machine(monkeypatch, apt=(), flatpaks=()):
    def run(argv, **kwargs):
        if argv[0] == "dpkg-query":
            out = "".join(f"ii  {name} 1.0\n" for name in apt)
        else:
            out = ""
        code = 0 if argv[:3] != ["flatpak", "info", "--user"] or argv[3] in flatpaks else 1
        return SimpleNamespace(returncode=code, stdout=out, stderr="")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)


def _save_applied(applied):
    state.save_state(_prior("homelab", applied), state.state_file())
