import subprocess

from dotfiles_setup.log import Logger


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
