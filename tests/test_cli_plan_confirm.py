import io

import pytest
from cli_support import _save_applied, machine
from dotfiles_setup import plan_confirm, rollback, state
from dotfiles_setup.cli import main


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def real_confirmation(isolated_dotfiles, monkeypatch):
    """isolated_dotfiles auto-approves the plan; these tests exercise the real prompt."""
    monkeypatch.setattr("dotfiles_setup.install_cmd.confirm_plan", plan_confirm.confirm_plan)


def _tty(monkeypatch, answer):
    monkeypatch.setattr("sys.stdin", Tty(answer + "\n"))
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)


def test_a_changing_plan_without_a_tty_or_yes_exits_5_before_any_step(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab"]) == 5
    assert flow_calls == []
    assert "pass --yes to apply" in capsys.readouterr().out


def test_exit_5_leaves_no_state_no_claude_settings_and_no_rollback_log(isolated_dotfiles, monkeypatch):
    _, tmp_path = isolated_dotfiles
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab"]) == 5
    assert state.load_state() is None
    assert not (tmp_path / "claude-home" / "settings.json").exists()
    assert not rollback.RollbackLog.for_home(tmp_path).path.exists()


def test_yes_applies_without_a_tty(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab", "--yes"]) == 0
    assert len(flow_calls) == 1


def test_the_short_flag_is_the_same_as_yes(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab", "-y"]) == 0
    assert len(flow_calls) == 1


def test_answering_yes_at_the_prompt_applies(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch)
    _tty(monkeypatch, "y")
    assert main(["apply", "--preset", "homelab"]) == 0
    assert len(flow_calls) == 1


def test_answering_no_exits_6_and_changes_nothing(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch)
    _tty(monkeypatch, "n")
    assert main(["apply", "--preset", "homelab"]) == 6
    assert flow_calls == []
    assert state.load_state() is None


def test_a_plan_with_nothing_to_change_applies_without_a_tty_or_yes(isolated_dotfiles, converged, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    assert main(["apply", "--preset", "homelab"]) == 0
    assert len(flow_calls) == 1


def test_dry_run_prints_the_plan_and_needs_no_confirmation(isolated_dotfiles, monkeypatch, capsys):
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab", "--dry-run"]) == 0
    assert "to install: curl, zsh" in capsys.readouterr().out


def test_yes_alone_does_not_remove_packages(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    machine(monkeypatch, apt=("htop", "zsh", "curl"))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["apply", "--preset", "homelab", "--yes"]) == 0
    assert flow_calls[0].removals == ()
    assert "pass --prune" in capsys.readouterr().out


def test_a_plan_with_only_held_removals_applies_without_a_tty_or_yes(isolated_dotfiles, converged, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("htop", "zsh", "curl"))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["apply", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ()


def test_an_interrupt_at_the_continue_prompt_exits_130_before_any_step(isolated_dotfiles, flow_calls, monkeypatch):
    class InterruptedTty(Tty):
        def readline(self, *args):
            raise KeyboardInterrupt

    machine(monkeypatch)
    monkeypatch.setattr("sys.stdin", InterruptedTty(""))
    assert main(["apply", "--preset", "homelab"]) == 130
    assert flow_calls == []


def test_yes_on_a_tty_asks_nothing_and_does_not_remove(isolated_dotfiles, flow_calls, monkeypatch):
    def refuse(prompt=""):
        raise AssertionError(f"unexpected prompt: {prompt}")

    machine(monkeypatch, apt=("htop", "zsh", "curl"))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", Tty(""))
    monkeypatch.setattr("builtins.input", refuse)
    assert main(["apply", "--preset", "homelab", "--yes"]) == 0
    assert flow_calls[0].removals == ()


def test_upgrade_lists_the_upgradable_packages_in_the_plan(isolated_dotfiles, monkeypatch, capsys):
    from types import SimpleNamespace

    def run(argv, **kwargs):
        out = "Inst openssl [1] (2 x)\n" if argv[:3] == ["apt-get", "-s", "dist-upgrade"] else ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)
    assert main(["apply", "--preset", "homelab", "--upgrade", "--dry-run"]) == 0
    assert "to upgrade (from local apt cache): openssl" in capsys.readouterr().out


def _legacy_overlay(monkeypatch, worktree=False):
    from dotfiles_setup import overlay

    monkeypatch.setattr(
        overlay, "find_overlay_root",
        lambda: next((r for r in (overlay.DEFAULT_OVERLAY_ROOT, overlay.LEGACY_OVERLAY_ROOT) if r.exists()), None),
    )
    overlay.LEGACY_OVERLAY_ROOT.mkdir()
    (overlay.LEGACY_OVERLAY_ROOT / "marker").write_text("kept")
    if worktree:
        (overlay.LEGACY_OVERLAY_ROOT / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt")
    return overlay


def test_the_plan_lists_the_pending_overlay_move(isolated_dotfiles, monkeypatch, capsys):
    machine(monkeypatch, apt=("zsh", "curl"))
    _legacy_overlay(monkeypatch)
    assert main(["apply", "--preset", "homelab", "--dry-run"]) == 0
    assert "to change: move" in capsys.readouterr().out


def test_a_pending_overlay_move_makes_the_plan_need_confirmation(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    overlay = _legacy_overlay(monkeypatch)
    assert main(["apply", "--preset", "homelab"]) == 5
    assert overlay.LEGACY_OVERLAY_ROOT.is_dir()
    assert not overlay.DEFAULT_OVERLAY_ROOT.exists()
    assert flow_calls == []


def test_declining_leaves_the_overlay_where_it_is(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    overlay = _legacy_overlay(monkeypatch)
    _tty(monkeypatch, "n")
    assert main(["apply", "--preset", "homelab"]) == 6
    assert (overlay.LEGACY_OVERLAY_ROOT / "marker").read_text() == "kept"
    assert not overlay.DEFAULT_OVERLAY_ROOT.exists()


def test_confirming_moves_the_overlay_and_hands_the_flow_the_new_path(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    overlay = _legacy_overlay(monkeypatch)
    assert main(["apply", "--preset", "homelab", "--yes"]) == 0
    assert not overlay.LEGACY_OVERLAY_ROOT.exists()
    assert (overlay.DEFAULT_OVERLAY_ROOT / "marker").read_text() == "kept"
    assert flow_calls[0].overlay_root == overlay.DEFAULT_OVERLAY_ROOT
    assert state.load_state().overlay_root == str(overlay.DEFAULT_OVERLAY_ROOT)


def test_a_linked_worktree_overlay_stops_with_exit_1_before_any_prompt(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch)
    overlay = _legacy_overlay(monkeypatch, worktree=True)
    assert main(["apply", "--preset", "homelab"]) == 1
    assert flow_calls == []
    assert overlay.LEGACY_OVERLAY_ROOT.is_dir()


def test_a_leftover_legacy_overlay_does_not_need_confirmation(isolated_dotfiles, converged, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    overlay = _legacy_overlay(monkeypatch)
    overlay.DEFAULT_OVERLAY_ROOT.mkdir()
    assert main(["apply", "--preset", "homelab"]) == 0
    assert len(flow_calls) == 1


@pytest.fixture
def identity_calls(monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.identity.ensure_git_identity", lambda **kw: calls.append(kw))
    return calls


def test_exit_5_does_not_prompt_for_a_git_identity(isolated_dotfiles, identity_calls, monkeypatch):
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab"]) == 5
    assert identity_calls == []


def test_exit_6_does_not_prompt_for_a_git_identity(isolated_dotfiles, identity_calls, monkeypatch):
    machine(monkeypatch)
    _tty(monkeypatch, "n")
    assert main(["apply", "--preset", "homelab"]) == 6
    assert identity_calls == []


def test_a_confirmed_apply_asks_for_the_git_identity_before_the_steps(isolated_dotfiles, identity_calls, flow_calls, monkeypatch):
    machine(monkeypatch)
    assert main(["apply", "--preset", "homelab", "--yes", "--reconfigure"]) == 0
    assert identity_calls == [{"force": True, "overlay_root": None}]


def test_upgrade_without_a_tty_or_yes_exits_5_even_when_nothing_else_changes(isolated_dotfiles, converged, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    assert main(["apply", "--preset", "homelab", "--upgrade"]) == 5
    assert flow_calls == []


def test_upgrade_with_yes_applies(isolated_dotfiles, converged, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("zsh", "curl"))
    assert main(["apply", "--preset", "homelab", "--upgrade", "--yes"]) == 0
    assert len(flow_calls) == 1


def test_prune_with_yes_removes_without_a_second_prompt(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("htop", "zsh", "curl"))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["apply", "--preset", "homelab", "--yes", "--prune"]) == 0
    assert flow_calls[0].removals == ("htop",)
