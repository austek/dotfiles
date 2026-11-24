import pytest
from dotfiles_setup.log import Logger
from dotfiles_setup.plan_confirm import (
    DECLINED_EXIT_CODE,
    NEEDS_YES_EXIT_CODE,
    confirm_plan,
)
from dotfiles_setup.plan_types import StepPlan, is_empty, render_plan


def _plan(step="apt", install=(), remove=(), upgrade=(), held=(), known=True, note=None, wanted=3, installed=3):
    return StepPlan(step, wanted, installed, tuple(install), tuple(remove), tuple(upgrade), tuple(held), note, known)


def _ask(answer):
    asked = []
    return asked, lambda prompt: asked.append(prompt) or answer


def test_a_plan_with_an_install_is_not_empty():
    assert not is_empty((_plan(install=("htop",)),))


@pytest.mark.parametrize("field", ["remove", "upgrade"])
def test_a_plan_with_a_remove_or_upgrade_is_not_empty(field):
    assert not is_empty((_plan(**{field: ("htop",)}),))


def test_a_config_change_makes_a_plan_non_empty():
    assert not is_empty((StepPlan("stow", 0, 0, change=("link zsh",)),))


def test_render_lists_config_changes(capsys):
    render_plan(Logger(dry_run=False), (StepPlan("stow", 0, 0, change=("link zsh", "link git")),))
    assert "to change: link zsh, link git" in capsys.readouterr().out


def test_unknown_steps_never_make_a_plan_non_empty():
    assert is_empty((_plan(), _plan(step="stow", known=False)))


def test_render_lists_counts_and_pending_names(capsys):
    render_plan(Logger(dry_run=False), (_plan(install=("htop", "jq"), wanted=10, installed=8),))
    out = capsys.readouterr().out
    assert "apt" in out
    assert "10" in out
    assert "htop" in out
    assert "jq" in out


def test_render_hides_rows_with_nothing_to_show(capsys):
    render_plan(Logger(dry_run=False), (StepPlan("stow", 0, 0), StepPlan("flatpak", 2, 2)))
    out = capsys.readouterr().out
    assert "stow" not in out
    assert "flatpak: 2 wanted, 2 installed" in out


def test_render_keeps_a_row_that_only_has_a_note(capsys):
    render_plan(Logger(dry_run=False), (StepPlan("snapd", 0, 0, note="skipped: --no-system"),))
    assert "skipped: --no-system" in capsys.readouterr().out


def test_render_marks_unknown_steps_and_lists_them_in_the_footer(capsys):
    render_plan(Logger(dry_run=False), (_plan(step="stow", known=False),))
    out = capsys.readouterr().out
    assert "checked during apply" in out
    assert "Also runs: stow" in out


def test_render_shows_held_removals_with_the_prune_hint(capsys):
    render_plan(Logger(dry_run=False), (_plan(step="removals", held=("htop",)),))
    out = capsys.readouterr().out
    assert "held back (pass --prune to remove): htop" in out


def test_held_removals_do_not_make_a_plan_non_empty():
    assert is_empty((_plan(step="removals", held=("htop",)),))


def test_render_labels_the_upgrade_list_as_from_the_local_cache(capsys):
    render_plan(Logger(dry_run=False), (_plan(upgrade=("curl",)),))
    assert "from local apt cache" in capsys.readouterr().out


def _confirm(plans, *, yes=False, interactive=True, dry_run=False, ask=None):
    return confirm_plan(
        Logger(dry_run=dry_run), plans, yes=yes, interactive=interactive, dry_run=dry_run,
        ask=ask or _ask("y")[1],
    )


def test_an_empty_plan_proceeds_without_asking():
    asked, ask = _ask("n")
    assert _confirm((_plan(),), ask=ask) is None
    assert asked == []


def test_an_empty_plan_proceeds_even_without_a_tty():
    assert _confirm((_plan(),), interactive=False) is None


def test_yes_answer_proceeds():
    asked, ask = _ask("y")
    assert _confirm((_plan(install=("htop",)),), ask=ask) is None
    assert asked == ["Continue? [y/N] "]


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe"])
def test_any_other_answer_declines_with_exit_6(answer):
    assert _confirm((_plan(install=("htop",)),), ask=_ask(answer)[1]) == DECLINED_EXIT_CODE == 6


def test_end_of_input_declines():
    def ask(prompt):
        raise EOFError

    assert _confirm((_plan(install=("htop",)),), ask=ask) == DECLINED_EXIT_CODE


def test_an_interrupt_propagates():
    def ask(prompt):
        raise KeyboardInterrupt

    plans = (_plan(install=("htop",)),)
    with pytest.raises(KeyboardInterrupt):
        _confirm(plans, ask=ask)


def test_yes_skips_the_prompt():
    asked, ask = _ask("n")
    assert _confirm((_plan(install=("htop",)),), yes=True, ask=ask) is None
    assert asked == []


def test_no_tty_without_yes_exits_5(capsys):
    asked, ask = _ask("y")
    assert _confirm((_plan(install=("htop",)),), interactive=False, ask=ask) == NEEDS_YES_EXIT_CODE == 5
    assert asked == []
    assert "pass --yes to apply" in capsys.readouterr().out


def test_no_tty_with_yes_proceeds():
    assert _confirm((_plan(install=("htop",)),), interactive=False, yes=True) is None


def test_dry_run_prints_the_plan_without_asking_and_lets_the_dry_steps_run(capsys):
    asked, ask = _ask("n")
    assert _confirm((_plan(install=("htop",)),), dry_run=True, interactive=False, ask=ask) is None
    assert asked == []
    assert "htop" in capsys.readouterr().out
