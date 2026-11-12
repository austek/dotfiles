import stat
import syslog
from types import SimpleNamespace

import pytest
from dotfiles_setup import transcript as tr
from dotfiles_setup.log import Logger


def lines(path):
    return [line.split(" ", 1)[1] for line in path.read_text().splitlines()]


def test_the_transcript_is_a_private_file_in_a_private_directory(tmp_path):
    result = tr.open_transcript(tmp_path / "logs", "20260101-000000")
    assert result.path == tmp_path / "logs/install-20260101-000000.log"
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "logs").stat().st_mode) == 0o700


def test_an_existing_directory_and_file_are_tightened_to_private_permissions(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir(mode=0o755)
    (directory / "install-s.log").write_text("earlier")
    (directory / "install-s.log").chmod(0o644)
    result = tr.open_transcript(directory, "s")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert result.path.read_text() == "earlier"


def test_no_transcript_is_returned_when_the_permissions_cannot_be_restricted(tmp_path, monkeypatch):
    def refuse(descriptor, mode):
        raise PermissionError

    monkeypatch.setattr(tr.os, "fchmod", refuse)
    assert tr.open_transcript(tmp_path / "logs", "s") is None


def test_only_the_newest_transcripts_are_kept(tmp_path):
    for day in range(1, 13):
        tr.open_transcript(tmp_path, f"202601{day:02d}-000000")
    names = sorted(p.name for p in tmp_path.glob("install-*.log"))
    assert len(names) == tr.KEPT_TRANSCRIPTS
    assert names[0] == "install-20260103-000000.log"
    assert names[-1] == "install-20260112-000000.log"


def test_other_files_in_the_directory_are_never_pruned(tmp_path):
    (tmp_path / "notes.txt").write_text("keep")
    for day in range(1, 13):
        tr.open_transcript(tmp_path, f"202601{day:02d}-000000")
    assert (tmp_path / "notes.txt").exists()


def test_an_unwritable_location_gives_no_transcript_instead_of_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert tr.open_transcript(blocker / "logs", "20260101-000000") is None


def test_each_non_blank_line_is_timestamped(tmp_path):
    result = tr.open_transcript(tmp_path, "s")
    result.write("one\n\n   \ntwo")
    written = result.path.read_text().splitlines()
    assert [line.split(" ", 1)[1] for line in written] == ["one", "two"]
    assert all(line[:4].isdigit() and "T" in line.split(" ", 1)[0] for line in written)


def test_a_write_that_fails_is_ignored(tmp_path):
    result = tr.Transcript(tmp_path / "missing/dir/file.log")
    result.write("lost")


def run_with(result=None, error=None):
    def run(argv, **kwargs):
        if error:
            raise error
        return result

    return run


def test_a_command_its_exit_code_and_captured_output_are_recorded():
    written = []
    done = SimpleNamespace(returncode=3, stdout="out line", stderr="err line")
    tr.recording(run_with(done), written.append)(["apt-get", "install", "a b"], capture_output=True)
    assert written == ["$ apt-get install 'a b' -> exit 3", "out line", "err line"]


def test_bytes_output_is_decoded_and_missing_output_is_skipped():
    written = []
    done = SimpleNamespace(returncode=0, stdout=b"caf\xc3\xa9\xff", stderr=None)
    tr.recording(run_with(done), written.append)(["cmd"])
    assert written == ["$ cmd -> exit 0", "caf\N{LATIN SMALL LETTER E WITH ACUTE}\N{REPLACEMENT CHARACTER}", ""]


def test_input_given_to_a_command_is_not_recorded():
    written = []
    tr.recording(run_with(SimpleNamespace(returncode=0, stdout="", stderr="")), written.append)(
        ["sudo", "tee", "/x"], input="SECRET")
    assert not any("SECRET" in entry for entry in written)


def test_the_result_is_passed_through_untouched():
    done = SimpleNamespace(returncode=0, stdout="", stderr="")
    assert tr.recording(run_with(done), lambda text: None)(["cmd"]) is done


def test_a_command_that_raises_is_recorded_and_the_error_propagates():
    written = []
    run = tr.recording(run_with(error=FileNotFoundError("no such")), written.append)
    with pytest.raises(FileNotFoundError):
        run(["nope"])
    assert written == ["$ nope raised FileNotFoundError: no such"]


def test_a_string_command_is_recorded_as_given():
    written = []
    tr.recording(run_with(SimpleNamespace(returncode=0, stdout="", stderr="")), written.append)("echo hi", shell=True)
    assert written[0] == "$ echo hi -> exit 0"


def test_logger_messages_reach_the_transcript_at_any_verbosity(tmp_path, syslog_lines):
    result = tr.open_transcript(tmp_path, "s")
    logger = Logger(dry_run=False, verbosity=0, transcript=result)
    logger.info("quiet info")
    logger.warn("a warning")
    assert lines(result.path) == ["quiet info", "a warning"]


def test_transcribe_writes_the_transcript_only(tmp_path, syslog_lines, capsys):
    result = tr.open_transcript(tmp_path, "s")
    Logger(dry_run=False, transcript=result).transcribe("detail")
    assert lines(result.path) == ["detail"]
    assert syslog_lines == []
    assert capsys.readouterr().out == ""


def test_a_failed_command_is_written_to_the_transcript_once(tmp_path, syslog_lines):
    result = tr.open_transcript(tmp_path, "s")
    logger = Logger(dry_run=False, transcript=result)
    run = tr.recording(lambda argv, **kw: SimpleNamespace(returncode=2, stdout="", stderr="boom"), logger.transcribe)
    logger.quiet_run(["cmd"], run=run)
    assert lines(result.path) == ["$ cmd -> exit 2", "boom"]
    assert (syslog.LOG_WARNING, "boom") in syslog_lines


def test_without_a_transcript_logging_still_works(syslog_lines):
    Logger(dry_run=False).info("hello")
    assert syslog_lines == [(syslog.LOG_INFO, "hello")]
