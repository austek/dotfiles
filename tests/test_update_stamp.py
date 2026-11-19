import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cli_support import _save_applied, fail_flow, machine
from dotfiles_setup import state, update_stamp
from dotfiles_setup.cli import Env, main
from dotfiles_setup.install_cmd import PERSIST_FAILED_EXIT_CODE

NOW = datetime(2026, 11, 19, 23, 59, 59, tzinfo=UTC)
NOW_DAYS = int(NOW.timestamp() // 86400)


def default_stamp() -> Path:
    return Path.home() / ".local" / "state" / "dotfiles" / "update-check"


def apply(*extra: str) -> int:
    return main(["apply", "--preset", "homelab", *extra], Env(clock=lambda: NOW))


def test_stamp_text_counts_utc_days_since_the_epoch():
    assert update_stamp.stamp_text(datetime(1970, 1, 2, 0, 0, 1, tzinfo=UTC)) == "LAST_EPOCH=1\n"
    assert update_stamp.stamp_text(NOW) == f"LAST_EPOCH={NOW_DAYS}\n"


def test_a_successful_apply_writes_the_stamp(isolated_dotfiles):
    assert apply() == 0
    assert default_stamp().read_text() == f"LAST_EPOCH={NOW_DAYS}\n"


def test_a_missing_stamp_directory_is_created_private(isolated_dotfiles, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "fresh"))
    apply()
    assert (tmp_path / "fresh" / "dotfiles").stat().st_mode & 0o777 == 0o700


def test_xdg_state_home_moves_the_stamp(isolated_dotfiles, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert apply() == 0
    assert (tmp_path / "xdg" / "dotfiles" / "update-check").read_text() == f"LAST_EPOCH={NOW_DAYS}\n"
    assert not default_stamp().exists()


def test_an_existing_stamp_is_replaced(isolated_dotfiles):
    default_stamp().parent.mkdir(parents=True)
    default_stamp().write_text("LAST_EPOCH=1\n")
    assert apply() == 0
    assert default_stamp().read_text() == f"LAST_EPOCH={NOW_DAYS}\n"


def test_a_dry_run_leaves_the_stamp_alone(isolated_dotfiles):
    assert apply("--dry-run") == 0
    assert not default_stamp().exists()


def test_a_failed_flow_leaves_the_stamp_alone(isolated_dotfiles, monkeypatch):
    fail_flow(monkeypatch)
    assert apply() == 1
    assert not default_stamp().exists()


def test_a_missing_preset_leaves_the_stamp_alone(isolated_dotfiles):
    assert main(["apply"], Env(clock=lambda: NOW)) == 2
    assert not default_stamp().exists()


def test_a_settings_drift_stop_leaves_the_stamp_alone(isolated_dotfiles, tmp_path):
    assert apply() == 0
    default_stamp().unlink()
    (tmp_path / "claude-home" / "settings.json").write_text('{"model": "edited by hand"}')
    assert apply() == 3
    assert not default_stamp().exists()


def test_a_failed_state_save_leaves_the_stamp_alone(isolated_dotfiles, monkeypatch):
    def refuse(machine_state, path):
        raise OSError("read-only file system")

    monkeypatch.setattr(state, "save_state", refuse)
    assert apply() == PERSIST_FAILED_EXIT_CODE
    assert not default_stamp().exists()


def test_an_interrupt_leaves_the_stamp_alone(isolated_dotfiles, monkeypatch):
    class InterruptedTty(io.StringIO):
        def isatty(self):
            return True

        def readline(self, *args):
            raise KeyboardInterrupt

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", InterruptedTty(""))
    assert apply() == 130
    assert not default_stamp().exists()


def test_a_stamp_write_failure_only_warns(isolated_dotfiles, monkeypatch, capsys):
    def refuse(path, text, mode):
        raise OSError("disk full")

    monkeypatch.setattr(update_stamp, "atomic_write_text", refuse)
    assert apply() == 0
    out = capsys.readouterr()
    assert f"Could not write the update reminder stamp {default_stamp()}: disk full" in out.out + out.err
    assert not default_stamp().exists()


def test_a_stamp_directory_failure_only_warns(isolated_dotfiles, monkeypatch, capsys):
    default_stamp().parent.parent.mkdir(parents=True)
    default_stamp().parent.write_text("in the way")
    assert apply() == 0
    assert f"Could not write the update reminder stamp {default_stamp()}:" in capsys.readouterr().out


@pytest.mark.parametrize("environ", [{}, {"XDG_STATE_HOME": ""}])
def test_the_default_location_is_under_the_home(environ):
    assert update_stamp.stamp_path(environ, Path("/h")) == Path("/h/.local/state/dotfiles/update-check")
