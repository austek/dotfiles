import json
import subprocess
from datetime import UTC, datetime

import pytest
from dotfiles_setup import doctor_checks
from dotfiles_setup.cli import Env, build_arg_parser, main
from dotfiles_setup.doctor_cache import write_cache
from dotfiles_setup.doctor_cmd import hint_line, run_doctor_fix
from dotfiles_setup.findings import CheckOutcome, Finding

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
BAD = [{"id": "b@m", "scope": "user", "errors": ["Path not found: /c (skills)"]}]
HEALTHY = [{"id": "a@m", "scope": "user"}]


@pytest.fixture(autouse=True)
def cache_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "dotfiles" / "doctor.json"


def _env(tmp_path, plugins=HEALTHY, calls=None):
    calls = [] if calls is None else calls

    def run(argv, **_):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(list(plugins)), stderr="")

    return Env(run=run, clock=lambda: NOW, home=tmp_path, state_dir=tmp_path / "cfg"), calls


def test_doctor_prints_the_finding_and_its_fix_and_exits_1(tmp_path, capsys):
    env, _ = _env(tmp_path, BAD)
    assert main(["doctor"], env) == 1
    out = capsys.readouterr().out
    assert "! b@m has load errors: Path not found: /c (skills)" in out
    assert "claude plugin uninstall b@m --scope user" in out
    assert "claude plugin install b@m --scope user" in out
    assert "1 problem found" in out
    assert "`dfctl doctor fix`" in out


def test_clean_machine_exits_0_without_a_fix_hint(tmp_path, capsys):
    env, _ = _env(tmp_path)
    assert main(["doctor"], env) == 0
    out = capsys.readouterr().out
    assert "No problems found." in out
    assert "dfctl doctor fix" not in out


def test_a_skipped_check_is_named_with_its_reason(tmp_path, capsys):
    env, _ = _env(tmp_path)
    main(["doctor"], env)
    assert "skipped stale_copies: no saved preset on this machine" in capsys.readouterr().out


def test_list_checks_prints_the_names_in_run_order_and_runs_nothing(tmp_path, capsys):
    env, calls = _env(tmp_path)
    assert main(["doctor", "--list-checks"], env) == 0
    assert capsys.readouterr().out.split() == ["stale_copies", "plugin_load_errors"]
    assert calls == []


def test_json_prints_findings_with_commands(tmp_path, capsys):
    env, _ = _env(tmp_path, BAD)
    assert main(["doctor", "--json"], env) == 1
    (finding,) = json.loads(capsys.readouterr().out)["findings"]
    assert finding["check"] == "plugin_load_errors"
    assert finding["commands"][0][:3] == ["claude", "plugin", "uninstall"]


def test_unknown_check_name_exits_2_and_runs_nothing(tmp_path, capsys):
    env, calls = _env(tmp_path)
    assert main(["doctor", "nope"], env) == 2
    assert "nope" in capsys.readouterr().err
    assert calls == []


def test_a_named_check_runs_only_that_check(tmp_path):
    env, calls = _env(tmp_path)
    main(["doctor", "plugin_load_errors"], env)
    assert calls == [("claude", "plugin", "list", "--json")]


def test_a_named_run_keeps_the_cached_findings_of_other_checks(tmp_path, cache_file):
    write_cache(cache_file, {"stale_copies": (Finding("stale_copies", "old shadow"),)}, NOW, merge=False)
    env, _ = _env(tmp_path)
    main(["doctor", "plugin_load_errors"], env)
    assert [f["check"] for f in json.loads(cache_file.read_text())["findings"]] == ["stale_copies"]


def test_a_full_run_replaces_the_whole_cache(tmp_path, cache_file):
    write_cache(cache_file, {"stale_copies": (Finding("stale_copies", "old shadow"),)}, NOW, merge=False)
    env, _ = _env(tmp_path, BAD)
    main(["doctor"], env)
    checks = [f["check"] for f in json.loads(cache_file.read_text())["findings"]]
    assert checks == ["plugin_load_errors"]


def test_a_crashing_check_becomes_a_finding_and_the_others_still_run(tmp_path, capsys, monkeypatch):
    def boom(_ctx):
        raise RuntimeError("kaput")

    monkeypatch.setitem(doctor_checks.CHECKS, "stale_copies", boom)
    env, _ = _env(tmp_path, BAD)
    assert main(["doctor"], env) == 1
    out = capsys.readouterr().out
    assert "check stale_copies crashed" in out
    assert "kaput" in out
    assert "b@m has load errors" in out


def test_an_unwritable_cache_directory_warns_and_keeps_the_exit_code(tmp_path, capsys, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    env, _ = _env(tmp_path)
    assert main(["doctor"], env) == 0
    assert "Could not write the doctor cache" in capsys.readouterr().out


def _fix_env(tmp_path, bad=("b@m",), fail=(), fixes=True):
    state = {"bad": list(bad)}
    calls = []

    def run(argv, **_):
        calls.append(tuple(argv))
        verb = argv[2]
        if verb == "list":
            plugins = [{"id": i, "scope": "user", "errors": ["x"]} for i in state["bad"]] + HEALTHY
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(plugins), stderr="")
        if (verb, argv[3]) in fail:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="denied")
        if verb == "install" and fixes:
            state["bad"].remove(argv[3])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    return Env(run=run, clock=lambda: NOW, home=tmp_path, state_dir=tmp_path / "cfg"), calls


def _fix(env, *flags, interactive=False, ask=input):
    args = build_arg_parser().parse_args(["doctor", "fix", *flags])
    return run_doctor_fix(args, env, interactive=interactive, ask=ask)


def _mutations(calls):
    return [c for c in calls if c[2] != "list"]


def test_fix_runs_each_commands_in_order_then_rechecks(tmp_path):
    env, calls = _fix_env(tmp_path)
    assert _fix(env, "-y") == 0
    assert calls == [
        ("claude", "plugin", "list", "--json"),
        ("claude", "plugin", "uninstall", "b@m", "--scope", "user"),
        ("claude", "plugin", "install", "b@m", "--scope", "user"),
        ("claude", "plugin", "list", "--json"),
    ]


def test_fix_stops_one_findings_commands_at_the_first_failure_but_runs_the_others(tmp_path):
    env, calls = _fix_env(tmp_path, bad=("b@m", "c@m"), fail=(("uninstall", "b@m"),))
    assert _fix(env, "-y") == 1
    assert ("claude", "plugin", "install", "b@m", "--scope", "user") not in calls
    assert ("claude", "plugin", "install", "c@m", "--scope", "user") in calls


def test_fix_never_runs_manual_findings_and_does_not_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(doctor_checks.CHECKS, "stale_copies", lambda _c: CheckOutcome((Finding("stale_copies", "shadow", advice="rm /x"),)))
    env, calls = _fix_env(tmp_path, bad=())
    assert _fix(env, interactive=False) == 1
    assert _mutations(calls) == []
    out = capsys.readouterr().out
    assert "rm /x" in out
    assert "none fixable" in out


def test_fix_without_a_terminal_or_yes_runs_nothing_and_exits_5(tmp_path):
    env, calls = _fix_env(tmp_path)
    assert _fix(env, interactive=False) == 5
    assert _mutations(calls) == []


def test_fix_declined_exits_6_and_runs_nothing(tmp_path):
    env, calls = _fix_env(tmp_path)
    assert _fix(env, interactive=True, ask=lambda _p: "n") == 6
    assert _mutations(calls) == []


def test_fix_confirmed_at_the_prompt_runs_the_commands(tmp_path):
    env, calls = _fix_env(tmp_path)
    assert _fix(env, interactive=True, ask=lambda _p: "y") == 0
    assert len(_mutations(calls)) == 2


def test_fix_yes_never_asks(tmp_path):
    def ask(_prompt):
        raise AssertionError("asked")

    env, _ = _fix_env(tmp_path)
    assert _fix(env, "-y", interactive=True, ask=ask) == 0


def test_fix_dry_run_prints_the_commands_and_runs_nothing(tmp_path, capsys):
    env, calls = _fix_env(tmp_path)
    assert _fix(env, "--dry-run") == 0
    assert _mutations(calls) == []
    assert "claude plugin install b@m --scope user" in capsys.readouterr().out


def test_fix_that_leaves_the_error_in_place_exits_1(tmp_path, capsys):
    env, _ = _fix_env(tmp_path, fixes=False)
    assert _fix(env, "-y") == 1
    assert "b@m has load errors" in capsys.readouterr().out


def test_fix_on_a_clean_machine_exits_0(tmp_path, capsys):
    env, calls = _fix_env(tmp_path, bad=())
    assert _fix(env) == 0
    assert "No problems found." in capsys.readouterr().out
    assert _mutations(calls) == []


def test_fix_with_an_unknown_check_exits_2(tmp_path):
    env, calls = _fix_env(tmp_path)
    assert _fix(env, "nope", "-y") == 2
    assert calls == []


def test_the_parser_reads_fix_as_the_first_name():
    assert build_arg_parser().parse_args(["doctor", "fix"]).names == ["fix"]


def test_hint_line_is_absent_without_findings():
    assert hint_line(()) is None


def test_hint_line_counts_problems_and_names_the_commands():
    line = hint_line((Finding("c", "t", commands=(("a",),)),))
    assert line == "1 problem found. Run `dfctl doctor` for details, `dfctl doctor fix` to apply the fixes."


def test_hint_line_does_not_offer_fix_when_nothing_is_fixable():
    line = hint_line((Finding("c", "t", advice="rm x"),))
    assert line == "1 problem found, none fixable by `dfctl doctor fix`. Run `dfctl doctor` for details."


def test_hint_line_says_how_many_are_fixable_when_some_are_manual():
    line = hint_line((Finding("c", "t", commands=(("a",),)), Finding("d", "u", advice="rm x")))
    assert line.startswith("2 problems found, 1 of 2 fixable. ")
