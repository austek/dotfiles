import io

import pytest
from cli_support import _save_applied, _write_optouts, machine
from dotfiles_setup import settings_drift, state
from dotfiles_setup.approval import applied_after_removals, confirm_removals
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.cli import main
from dotfiles_setup.log import Logger
from dotfiles_setup.tooling import Tooling


def _tooling(tmp_path, monkeypatch, apt=(), flatpaks=()):
    machine(monkeypatch, apt, flatpaks)
    return Tooling(Logger(dry_run=False), tmp_path)


def test_applied_reports_pin_entries(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, apt=("k9s",))
    applied = applied_after_removals(t, frozenset({"zsh"}), ("github:derailed/k9s",), [])
    assert applied == ("github:derailed/k9s", "zsh")
    assert applied_after_removals(t, frozenset({"zsh"}), ("github:derailed/k9s",), ["github:derailed/k9s"]) == ("zsh",)


def _ask(answer):
    asked = []
    return asked, lambda prompt: asked.append(prompt) or answer


@pytest.mark.parametrize("answer", ["y", "yes", "Y", "YES"])
def test_rule007_confirm_yes_applies(answer, capsys):
    asked, ask = _ask(answer)
    assert confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=True, ask=ask)
    assert asked == ["Remove these packages? [y/N] "]
    assert "htop" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe"])
def test_rule007_confirm_other_answers_decline(answer, capsys):
    _, ask = _ask(answer)
    assert not confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=True, ask=ask)
    assert "Removals declined; they will be offered again next run." in capsys.readouterr().out


def test_rule007_confirm_non_interactive_declines_without_prune(capsys):
    asked, ask = _ask("y")
    assert not confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=False, ask=ask)
    assert asked == []
    assert "pass --prune to apply" in capsys.readouterr().out


def test_confirm_prune_applies_without_asking():
    asked, ask = _ask("n")
    assert confirm_removals(Logger(dry_run=False), ("htop",), prune=True, interactive=False, ask=ask)
    assert asked == []


def test_confirm_with_nothing_pending_is_silent(capsys):
    asked, ask = _ask("y")
    assert not confirm_removals(Logger(dry_run=False), (), prune=True, interactive=True, ask=ask)
    assert asked == []
    assert capsys.readouterr().out == ""


def test_confirm_lists_manual_entries_separately(capsys):
    confirm_removals(Logger(dry_run=False), ("htop", "flatpak:org.x.App", "sdkman"), prune=True, interactive=False)
    out = capsys.readouterr().out
    assert "htop" in out
    assert "flatpak:org.x.App" in out
    assert "dropped, remove manually" in out
    assert "sdkman" in out


def _raise(error):
    def ask(prompt):
        raise error

    return ask


def test_rule007_confirm_treats_end_of_input_as_declined(capsys):
    assert not confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=True, ask=_raise(EOFError))
    assert "Removals declined; they will be offered again next run." in capsys.readouterr().out


def test_confirm_lets_an_interrupt_propagate():
    logger = Logger(dry_run=False)
    ask = _raise(KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        confirm_removals(logger, ("htop",), prune=False, interactive=True, ask=ask)


def test_an_interrupt_at_the_prompt_exits_130_before_any_step(isolated_dotfiles, flow_calls, monkeypatch):
    class InterruptedTty(io.StringIO):
        def isatty(self):
            return True

        def readline(self, *args):
            raise KeyboardInterrupt

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", InterruptedTty(""))
    assert main(["install", "--preset", "homelab"]) == 130
    assert flow_calls == []
    assert state.load_state().applied_package_names == ("curl", "htop", "zsh")


def test_an_interrupt_at_the_prompt_leaves_the_claude_settings_unwritten(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles

    class InterruptedTty(io.StringIO):
        def isatty(self):
            return True

        def readline(self, *args):
            raise KeyboardInterrupt

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", InterruptedTty(""))
    assert main(["install", "--preset", "homelab"]) == 130
    assert not (tmp_path / "claude-home" / "settings.json").exists()
    assert not settings_drift.baseline_path(tmp_path / "state").exists()


def test_confirm_with_only_manual_entries_lists_them_without_asking(capsys):
    asked, ask = _ask("y")
    assert not confirm_removals(Logger(dry_run=False), ("sdkman",), prune=False, interactive=True, ask=ask)
    assert asked == []
    assert "remove manually: sdkman" in capsys.readouterr().out


def test_applied_keeps_installed_pending_names_that_were_not_removed(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, apt=("htop",))
    applied = applied_after_removals(t, frozenset({"zsh"}), ("htop",), [])
    assert applied == ("htop", "zsh")


def test_rule009_applied_drops_removed_names(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, apt=("htop", "vim"))
    applied = applied_after_removals(t, frozenset({"zsh"}), ("htop", "vim"), ["htop"])
    assert applied == ("vim", "zsh")


def test_applied_drops_pending_names_that_are_not_installed(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch)
    assert applied_after_removals(t, frozenset({"zsh"}), ("htop",), []) == ("zsh",)


def test_applied_drops_manual_entries(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch)
    assert applied_after_removals(t, frozenset({"zsh"}), ("sdkman",), []) == ("zsh",)


def test_applied_keeps_flatpaks_with_their_prefix(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, flatpaks=("org.x.App", "org.y.App"))
    applied = applied_after_removals(
        t, frozenset({"zsh"}), ("flatpak:org.x.App", "flatpak:org.y.App"), ["flatpak:org.y.App"],
    )
    assert applied == ("flatpak:org.x.App", "zsh")


def test_prune_applies_non_interactively(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("htop",)


def test_rule009_declined_removals_stay_in_applied_state(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ()
    assert state.load_state().applied_package_names == ("curl", "htop", "zsh")


def test_rule009_completed_removals_leave_applied_state(isolated_dotfiles, monkeypatch):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))

    def run_install(inputs):
        inputs.removed.extend(inputs.removals)
        return InstallResult(True, 0, "")

    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", run_install)
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert state.load_state().applied_package_names == ("curl", "zsh")


def test_interactive_yes_approves_removals(isolated_dotfiles, flow_calls, monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", Tty("y\n"))
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ("htop",)


def test_migration_offers_installed_fork_only_packages(isolated_dotfiles, flow_calls, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    machine(monkeypatch, apt=("curl", "slack-desktop", "zsh"))
    _write_optouts(tmp_path, "zsh\ncurl\nslack-desktop\nnever-installed\n")
    _save_applied(("curl", "zsh"))
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("slack-desktop",)


def test_prompt_lists_only_installed_removals(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "vim", "zsh"))
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("htop",)
    assert "vim" not in capsys.readouterr().out


def test_no_prompt_when_no_removal_is_installed(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    machine(monkeypatch)
    _save_applied(("curl", "sdkman", "vim", "zsh"))
    monkeypatch.setattr("sys.stdin", Tty("y\n"))
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("no prompt expected"))
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ()
    out = capsys.readouterr().out
    assert "vim" not in out
    assert out.count("remove manually") == 1


def test_rule007_dry_run_lists_removals_and_does_not_prompt(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("no prompt expected"))
    assert main(["install", "--preset", "homelab", "--dry-run", "--prune"]) == 0
    assert flow_calls[0].removals == ()
    assert "htop" in capsys.readouterr().out
