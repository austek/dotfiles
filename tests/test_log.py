import subprocess
import syslog
from types import SimpleNamespace

import pytest
from dotfiles_setup.log import Logger


@pytest.mark.parametrize(("method", "priority"), [
    ("info", syslog.LOG_INFO), ("success", syslog.LOG_INFO), ("banner", syslog.LOG_INFO),
    ("step", syslog.LOG_NOTICE), ("warn", syslog.LOG_WARNING), ("error", syslog.LOG_ERR),
])
def test_every_message_reaches_syslog_at_verbosity_zero(method, priority, syslog_lines):
    getattr(Logger(dry_run=False, verbosity=0), method)("hello")
    assert syslog_lines == [(priority, "hello")]


def test_a_dry_run_notice_is_marked_in_syslog(syslog_lines):
    assert Logger(dry_run=True).dry_run_notice("Would do it")
    assert syslog_lines == [(syslog.LOG_INFO, "[dry-run] Would do it")]


def test_nothing_is_logged_for_a_dry_run_notice_outside_a_dry_run(syslog_lines):
    assert not Logger(dry_run=False).dry_run_notice("Would do it")
    assert syslog_lines == []


def test_record_writes_one_entry_per_non_blank_line_and_nothing_to_the_screen(syslog_lines, capsys):
    Logger(dry_run=False).record("first\n\n  \nsecond\n", "warning")
    assert syslog_lines == [(syslog.LOG_WARNING, "first"), (syslog.LOG_WARNING, "second")]
    assert capsys.readouterr().out == ""


def test_a_failed_quiet_command_is_logged_with_its_output(syslog_lines, capsys):
    run = lambda argv, **kw: SimpleNamespace(returncode=2, stdout="", stderr="boom\n")
    Logger(dry_run=False).quiet_run(["cmd", "--flag"], run=run)
    assert syslog_lines == [(syslog.LOG_WARNING, "cmd --flag exited 2"), (syslog.LOG_WARNING, "boom")]
    assert capsys.readouterr().err == "boom\n"


def test_a_failed_command_streamed_at_verbosity_two_is_logged_with_its_exit_status_only(syslog_lines):
    run = lambda argv, **kw: SimpleNamespace(returncode=5, stdout=None, stderr=None)
    Logger(dry_run=False, verbosity=2).quiet_run(["cmd", "--flag"], run=run)
    assert syslog_lines == [(syslog.LOG_WARNING, "cmd --flag exited 5")]


def test_a_successful_command_streamed_at_verbosity_two_logs_nothing(syslog_lines):
    run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=None, stderr=None)
    Logger(dry_run=False, verbosity=2).quiet_run(["cmd"], run=run)
    assert syslog_lines == []


def test_a_successful_quiet_command_logs_nothing(syslog_lines):
    run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="out", stderr="")
    Logger(dry_run=False).quiet_run(["cmd"], run=run)
    assert syslog_lines == []


def test_info_hidden_at_verbosity_zero(capsys):
    Logger(dry_run=False, verbosity=0).info("hello")
    assert capsys.readouterr().out == ""


def test_info_shown_at_verbosity_one(capsys):
    Logger(dry_run=False, verbosity=1).info("hello")
    assert "[INFO] hello" in capsys.readouterr().out


def test_success_hidden_at_verbosity_zero(capsys):
    Logger(dry_run=False, verbosity=0).success("done")
    assert capsys.readouterr().out == ""


def test_banner_always_shown(capsys):
    Logger(dry_run=False, verbosity=0).banner("done")
    assert "[SUCCESS] done" in capsys.readouterr().out


def test_step_always_shown(capsys):
    Logger(dry_run=False, verbosity=0).step("Starting...")
    assert "==> Starting..." in capsys.readouterr().out


def test_warn_always_shown(capsys):
    Logger(dry_run=False, verbosity=0).warn("careful")
    assert "[WARNING] careful" in capsys.readouterr().out


def test_error_goes_to_stderr_not_stdout(capsys):
    Logger(dry_run=False, verbosity=0).error("bad")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[ERROR] bad" in captured.err


def test_dry_run_notice_prints_and_returns_true_when_dry_run(capsys):
    logger = Logger(dry_run=True, verbosity=0)
    assert logger.dry_run_notice("would do X") is True
    assert "[DRY-RUN] would do X" in capsys.readouterr().out


def test_dry_run_notice_returns_false_and_prints_nothing_when_not_dry_run(capsys):
    logger = Logger(dry_run=False, verbosity=0)
    assert logger.dry_run_notice("would do X") is False
    assert capsys.readouterr().out == ""


def test_quiet_run_suppresses_output_on_success(capsys):
    def fake_run(argv, capture_output=True, text=True):
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    logger = Logger(dry_run=False, verbosity=0)
    result = logger.quiet_run(["cmd"], run=fake_run)
    assert result.returncode == 0
    assert capsys.readouterr().out == ""


def test_quiet_run_prints_captured_output_on_failure(capsys):
    def fake_run(argv, capture_output=True, text=True):
        return subprocess.CompletedProcess(argv, 1, stdout="oops\n", stderr="")

    logger = Logger(dry_run=False, verbosity=0)
    result = logger.quiet_run(["cmd"], run=fake_run)
    assert result.returncode == 1
    assert "oops" in capsys.readouterr().err


def test_quiet_run_streams_directly_at_verbosity_two():
    calls = []

    def fake_run(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    logger = Logger(dry_run=False, verbosity=2)
    result = logger.quiet_run(["cmd"], run=fake_run)
    assert calls == [["cmd"]]
    assert result.returncode == 0
