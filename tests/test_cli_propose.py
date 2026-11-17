import pytest
from dotfiles_setup import worktree
from dotfiles_setup.cli import build_arg_parser, main


def test_propose_dispatches_to_run_propose(monkeypatch):
    monkeypatch.setattr("dotfiles_setup.cli.run_propose", lambda: 5)
    assert main(["propose"]) == 5


def test_propose_help_says_main_checkout_only(capsys):
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["propose", "-h"])
    out = capsys.readouterr().out.replace("\n", " ")
    assert "main checkout" in out
    assert "open a PR" in out


def test_top_level_help_lists_propose(capsys):
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["-h"])
    out = capsys.readouterr().out
    assert "propose" in out
    assert "dfctl propose" in out


def test_apply_refuses_when_the_shared_guard_reports_a_linked_worktree(isolated_dotfiles, monkeypatch, capsys):
    monkeypatch.setattr(worktree, "is_linked_worktree", lambda root: True)
    assert main(["apply", "--preset", "homelab"]) == 1
    assert "linked worktree" in capsys.readouterr().err
