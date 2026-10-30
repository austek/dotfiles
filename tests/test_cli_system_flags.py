import pytest
from dotfiles_setup import cli


def parse(*args):
    return cli.build_arg_parser().parse_args(["install", *args])


def test_the_system_stage_is_decided_by_a_check_unless_a_flag_says_otherwise():
    assert parse().system == "auto"


def test_system_forces_the_stage_and_no_system_skips_it():
    assert parse("--system").system == "always"
    assert parse("--no-system").system == "never"


def test_system_and_no_system_cannot_be_combined(capsys):
    with pytest.raises(SystemExit):
        parse("--system", "--no-system")
    assert "not allowed with argument" in capsys.readouterr().err
