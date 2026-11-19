from types import SimpleNamespace

from cli_support import stub_subprocess
from dotfiles_setup import path_dirs, state
from dotfiles_setup.cli import Env, main


def test_main_overlay_clone_clones_to_default_dest(tmp_path, monkeypatch):
    default_root = tmp_path / "dotfiles-overlay"
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", default_root)
    calls = stub_subprocess(monkeypatch, stdout="")
    assert main(["overlay", "clone", "--repo", "git@github.com:you/dotfiles-overlay.git"]) == 0
    assert calls == [["git", "clone", "git@github.com:you/dotfiles-overlay.git", str(default_root)]]


def test_the_private_command_still_clones_and_says_it_is_deprecated(tmp_path, monkeypatch, capsys):
    default_root = tmp_path / "dotfiles-overlay"
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", default_root)
    calls = stub_subprocess(monkeypatch, stdout="")
    assert main(["private", "clone", "--repo", "git@example.com/x.git"]) == 0
    assert calls == [["git", "clone", "git@example.com/x.git", str(default_root)]]
    assert "'dfctl private' is deprecated; use 'dfctl overlay'." in capsys.readouterr().err


def test_the_overlay_command_prints_no_deprecation_notice(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", tmp_path / "dotfiles-overlay")
    stub_subprocess(monkeypatch, stdout="")
    main(["overlay", "clone", "--repo", "git@example.com/x.git"])
    assert "deprecated" not in capsys.readouterr().err


def test_main_overlay_clone_honors_dest_override(tmp_path):
    dest = tmp_path / "custom-dest"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    argv = ["overlay", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]
    assert main(argv, Env(run=run)) == 0
    assert calls[0][-1] == str(dest)


def _save_preset(tmp_path, preset_name):
    state.save_state(state.MachineState(
        preset_name=preset_name, backend="apt", package_file="x", applied_package_names=(),
        overlay_root=None, created_at="t", updated_at="t",
    ), state.state_file(tmp_path))


def test_main_foothold_restart_restarts_the_installed_footholds(tmp_path, monkeypatch):
    _save_preset(tmp_path, "homelab")
    restarted = []
    monkeypatch.setattr(
        "dotfiles_setup.foothold.restart_footholds",
        lambda logger, run, path_entries: restarted.append(path_entries) or True,
    )
    assert main(["foothold", "restart"], Env(state_dir=tmp_path)) == 0
    assert restarted == [path_dirs.load(Env().dotfiles_dir, None).value]


def test_main_foothold_restart_fails_when_the_restart_fails(tmp_path, monkeypatch):
    _save_preset(tmp_path, "homelab")
    monkeypatch.setattr("dotfiles_setup.foothold.restart_footholds", lambda logger, run, path_entries: False)
    assert main(["foothold", "restart"], Env(state_dir=tmp_path)) == 1


def test_main_foothold_restart_without_a_saved_preset_exits_2(tmp_path):
    assert main(["foothold", "restart"], Env(state_dir=tmp_path)) == 2


def test_main_overlay_clone_dry_run_does_not_clone(tmp_path, monkeypatch, capsys):
    def unexpected_run(argv, **kwargs):
        raise AssertionError("git clone should not run in dry-run mode")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", unexpected_run)

    dest = tmp_path / "dotfiles-overlay"
    assert main(["overlay", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest), "--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert not dest.exists()


def test_main_overlay_clone_returns_nonzero_on_git_failure(tmp_path, monkeypatch, capsys):
    stub_subprocess(monkeypatch, returncode=128, stdout="", stderr="fatal: repository not found")
    dest = tmp_path / "dotfiles-overlay"
    assert main(["overlay", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]) == 128
    assert "not found" in capsys.readouterr().err
