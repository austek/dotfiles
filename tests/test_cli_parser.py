from datetime import UTC, datetime

import pytest
from dotfiles_setup.cli import Env, build_arg_parser, main


def test_preset_is_optional_at_parse_time():
    args = build_arg_parser().parse_args(["install"])
    assert args.preset is None


def test_preset_accepts_any_value_at_parse_time():
    """Preset existence is validated by presets.load_preset(), not argparse —
    an unknown name here is a runtime FileNotFoundError, not a parse error."""
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "bogus"])
    assert args.preset == "bogus"


@pytest.mark.parametrize("preset", ["work", "personal", "homelab"])
def test_preset_accepts_valid_values(preset):
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", preset])
    assert args.preset == preset


@pytest.mark.parametrize(("flags", "expected"), [([], False), (["--dry-run"], True)])
def test_dry_run_flag(flags, expected):
    args = build_arg_parser().parse_args(["install", "--preset", "work", *flags])
    assert args.dry_run is expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [([], 0), (["-v"], 1), (["-vv"], 2), (["-vvv"], 3)],
)
def test_verbosity_flag(flags, expected):
    args = build_arg_parser().parse_args(["install", "--preset", "work", *flags])
    assert args.verbosity == expected


def test_verbosity_accumulates_across_distinct_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-v", "-vv"])
    assert args.verbosity == 3


def test_main_without_command_prints_help_and_returns_1(capsys):
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "install" in out


def test_top_level_help_lists_install_subcommand_and_examples(capsys):
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["-h"])
    out = capsys.readouterr().out
    assert "install" in out
    assert "Examples:" in out
    assert "dotfiles-setup install --preset work" in out


def test_private_clone_requires_subcommand():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["private"])


def test_private_clone_requires_repo():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["private", "clone"])


def test_private_clone_dest_defaults_to_none():
    parser = build_arg_parser()
    args = parser.parse_args(["private", "clone", "--repo", "git@github.com:you/dotfiles-private.git"])
    assert args.dest is None


def test_foothold_requires_subcommand():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["foothold"])


def test_env_now_iso_uses_clock():
    env = Env(clock=lambda: datetime(2030, 1, 2, tzinfo=UTC))
    assert env.now_iso() == "2030-01-02T00:00:00+00:00"


def test_each_subcommand_parser_is_built_by_its_own_function():
    parser = build_arg_parser()
    assert parser.parse_args(["install", "-vv", "--force"]).verbosity == 2
    assert parser.parse_args(["private", "clone", "--repo", "x"]).private_command == "clone"


def test_prune_flag_parses():
    assert build_arg_parser().parse_args(["install", "--prune"]).prune is True
    assert build_arg_parser().parse_args(["install"]).prune is False
