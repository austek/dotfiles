import json
from datetime import UTC, datetime

import pytest
from cli_support import _add_preset, fail_flow
from dotfiles_setup import overlay, state
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.backends.apt import AptBackend
from dotfiles_setup.cli import Env, main


def test_main_returns_zero_for_valid_preset(isolated_dotfiles):
    assert main(["install", "--preset", "homelab"]) == 0


def test_main_prints_dry_run_banner_when_requested(isolated_dotfiles, capsys):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert "DRY-RUN MODE" in capsys.readouterr().out


def test_main_does_not_print_dry_run_banner_otherwise(isolated_dotfiles, capsys):
    main(["install", "--preset", "homelab"])
    assert "DRY-RUN MODE" not in capsys.readouterr().out


def test_install_reports_backend_failure(isolated_dotfiles, monkeypatch):
    fail_flow(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 1


def test_install_reports_a_failure_with_no_message(isolated_dotfiles, capsys, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: InstallResult(False, 3, ""))
    assert main(["install", "--preset", "homelab"]) == 3
    assert "exit code 3" in capsys.readouterr().err


def test_dry_run_skips_git_identity(isolated_dotfiles, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.identity.ensure_git_identity",
        lambda **kw: calls.append(kw) or None,
    )
    main(["install", "--preset", "homelab", "--dry-run"])
    assert calls == []


def test_dry_run_hands_the_flow_the_packages_it_would_install(isolated_dotfiles, flow_calls):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert flow_calls[0].packages == frozenset({"zsh", "curl"})


def test_install_forwards_verbosity_to_the_flow(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab", "-vv"]) == 0
    assert flow_calls[0].t.logger.verbosity == 2


def test_install_passes_the_overlay_root_to_the_flow(isolated_dotfiles, flow_calls, monkeypatch, tmp_path):
    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].overlay_root == private_root


def test_install_passes_no_overlay_root_when_there_is_none(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].overlay_root is None


def test_install_hands_the_flow_the_preset_and_packages(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].preset_name == "homelab"
    assert flow_calls[0].packages == frozenset({"zsh", "curl"})


def test_install_raises_helpful_error_for_unknown_preset(isolated_dotfiles, capsys):
    assert main(["install", "--preset", "nonexistent"]) == 1
    assert "nonexistent" in capsys.readouterr().err


def test_install_checks_for_dotfiles_updates_before_the_install_runs(isolated_dotfiles, monkeypatch):
    order = []
    monkeypatch.setattr("dotfiles_setup.update.pull_if_behind", lambda repo, logger: order.append(repo) or False)
    monkeypatch.setattr(
        "dotfiles_setup.install_flow.run_install", lambda inputs: order.append("flow") or InstallResult(True, 0, ""),
    )
    main(["install", "--preset", "homelab"])
    assert order == [isolated_dotfiles[0], "flow"]


def test_install_pulls_private_overlay_after_dotfiles(isolated_dotfiles, monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    order = []
    monkeypatch.setattr("dotfiles_setup.overlay.find_overlay_root", lambda: private)
    monkeypatch.setattr("dotfiles_setup.update.pull_if_behind", lambda repo, logger: order.append("dotfiles") or False)
    monkeypatch.setattr("dotfiles_setup.update.pull_overlay_if_git", lambda root, logger: order.append(root) or False)
    main(["install", "--preset", "homelab"])
    assert order == ["dotfiles", private]


def test_install_updates_claude_plugins_after_a_successful_install(isolated_dotfiles, plugin_updates):
    assert main(["install", "--preset", "homelab"]) == 0
    assert len(plugin_updates) == 1


def test_install_sets_up_the_presets_footholds(isolated_dotfiles, foothold_syncs):
    assert main(["install", "--preset", "homelab"]) == 0
    assert foothold_syncs == [("main", "burst")]


def test_install_of_a_preset_without_footholds_asks_for_none(isolated_dotfiles, foothold_syncs):
    assert main(["install", "--preset", "work"]) == 0
    assert foothold_syncs == [()]


def test_install_syncs_the_new_presets_footholds_when_the_preset_changes(isolated_dotfiles, foothold_syncs):
    dotfiles_dir, _ = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    assert main(["install", "--preset", "homelab"]) == 0
    assert main(["install", "--preset", "personal"]) == 0
    assert foothold_syncs == [("main", "burst"), ()]


def test_install_skips_the_foothold_when_the_install_fails(isolated_dotfiles, foothold_syncs, monkeypatch):
    fail_flow(monkeypatch, "boom")
    main(["install", "--preset", "homelab"])
    assert foothold_syncs == []


def test_install_skips_claude_plugin_update_when_the_install_fails(isolated_dotfiles, plugin_updates, monkeypatch):
    fail_flow(monkeypatch, "boom")
    main(["install", "--preset", "homelab"])
    assert plugin_updates == []


def test_install_without_preset_or_saved_state_fails(isolated_dotfiles, capsys):
    assert main(["install"]) == 2
    assert "pass --preset" in capsys.readouterr().err


def test_install_without_preset_fails_before_touching_the_checkout(isolated_dotfiles, monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.plan._prepare_checkout", lambda *a: calls.append(a))
    assert main(["install"]) == 2
    assert calls == []


def test_install_without_preset_reuses_the_saved_one(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    assert main(["install"]) == 0
    assert state.load_state().preset_name == "homelab"


def test_install_preset_overrides_the_saved_one(isolated_dotfiles):
    dotfiles_dir, _tmp = isolated_dotfiles
    (dotfiles_dir / "presets" / "other.json").write_text(json.dumps({
        "description": "test", "package_files": ["apt_common.txt"], "backend_overrides": {},
    }))
    main(["install", "--preset", "homelab"])
    assert main(["install", "--preset", "other"]) == 0
    assert state.load_state().preset_name == "other"


def test_install_without_preset_reports_an_unknown_saved_preset(isolated_dotfiles):
    dotfiles_dir, _tmp = isolated_dotfiles
    main(["install", "--preset", "homelab"])
    (dotfiles_dir / "presets" / "homelab.json").unlink()
    assert main(["install"]) == 1


def test_install_passes_overlay_root_to_git_identity(isolated_dotfiles, monkeypatch, tmp_path):
    """The overlay must be known before ensure_git_identity runs so a private
    overlay's git/gitconfig.local can suppress the interactive prompt."""
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.identity.ensure_git_identity",
        lambda **kw: calls.append(kw) or tmp_path / "gitconfig.local",
    )
    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)

    assert main(["install", "--preset", "homelab"]) == 0
    assert calls[0]["overlay_root"] == private_root


def test_install_uses_injected_clock_and_paths(isolated_dotfiles, tmp_path):
    dotfiles_dir, _ = isolated_dotfiles
    clock_value = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    env = Env(
        clock=lambda: clock_value, claude_home=tmp_path / "injected-claude",
        state_dir=tmp_path / "injected-state", dotfiles_dir=dotfiles_dir,
    )
    assert main(["install", "--preset", "homelab"], env) == 0
    saved = state.load_state(tmp_path / "injected-state" / "state.json")
    assert saved.created_at == clock_value.isoformat()
    assert (tmp_path / "injected-claude" / "settings.json").is_file()
    assert not (tmp_path / "injected-state" / "packages").exists()


def test_install_builds_backend_through_injected_factory(isolated_dotfiles):
    dotfiles_dir, _ = isolated_dotfiles
    seen = []

    def factory(directory, overrides):
        seen.append((directory, overrides))
        return AptBackend(dotfiles_dir=directory, backend_overrides=overrides)

    assert main(["install", "--preset", "homelab"], Env(dotfiles_dir=dotfiles_dir, backend_factory=factory)) == 0
    assert seen == [(dotfiles_dir, {})]


def test_install_force_flag_reaches_the_flow(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab", "--force"]) == 0
    assert flow_calls[0].force is True


def test_force_is_off_by_default(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].force is False


def test_a_failed_step_offers_a_rollback(isolated_dotfiles, monkeypatch):
    offered = []
    failed = InstallResult(False, 1, "Step 'x' failed.", rollback_pending=True)
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: failed)
    monkeypatch.setattr("dotfiles_setup.rollback.offer_rollback", lambda ctx, interactive: offered.append(ctx))
    assert main(["install", "--preset", "homelab"]) == 1
    assert len(offered) == 1


def test_a_failure_with_nothing_to_roll_back_offers_nothing(isolated_dotfiles, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: InstallResult(False, 1, "no"))
    monkeypatch.setattr(
        "dotfiles_setup.rollback.offer_rollback", lambda ctx, interactive: pytest.fail("no rollback expected"),
    )
    assert main(["install", "--preset", "homelab"]) == 1


def test_install_refuses_to_run_from_a_linked_worktree(isolated_dotfiles, flow_calls, capsys):
    dotfiles_dir, _ = isolated_dotfiles
    (dotfiles_dir / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt")
    assert main(["install", "--preset", "homelab"]) == 1
    assert "linked worktree" in capsys.readouterr().err
    assert flow_calls == []


def test_a_dry_run_is_allowed_from_a_linked_worktree(isolated_dotfiles, flow_calls):
    dotfiles_dir, _ = isolated_dotfiles
    (dotfiles_dir / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt")
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert len(flow_calls) == 1


def test_install_runs_from_a_main_checkout(isolated_dotfiles, flow_calls):
    dotfiles_dir, _ = isolated_dotfiles
    (dotfiles_dir / ".git").mkdir()
    assert main(["install", "--preset", "homelab"]) == 0
    assert len(flow_calls) == 1


def test_dry_run_install_writes_nothing_to_disk(isolated_dotfiles):
    _, tmp_path = isolated_dotfiles
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert not list((tmp_path / "claude-home").rglob("*"))
    assert not (tmp_path / "state" / "state.json").exists()
    assert not (tmp_path / "state" / "claude-profiles").exists()
