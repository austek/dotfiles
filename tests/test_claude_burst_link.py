import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "claude-burst-link"


def _home(tmp_path: Path) -> Path:
    claude = tmp_path / ".claude"
    (claude / "projects").mkdir(parents=True)
    (claude / "backups").mkdir()
    for name in ("settings.json", ".credentials.json", ".hidden", "..odd"):
        (claude / name).write_text(name)
    return claude


def _link(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT)], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", **env},
        capture_output=True, text=True, check=True,
    )


def test_prints_the_default_burst_dir(tmp_path):
    _home(tmp_path)
    assert _link(tmp_path).stdout.strip() == str(tmp_path / ".claude-burst")


def test_links_everything_except_the_login(tmp_path):
    claude = _home(tmp_path)
    _link(tmp_path)
    burst = tmp_path / ".claude-burst"
    assert sorted(p.name for p in burst.iterdir()) == ["..odd", ".hidden", "projects", "settings.json"]
    assert all((burst / p.name).resolve() == p.resolve() for p in burst.iterdir())
    assert (burst / "settings.json").resolve() == claude / "settings.json"


def test_keeps_the_burst_login_and_account_file(tmp_path):
    _home(tmp_path)
    burst = tmp_path / ".claude-burst"
    burst.mkdir()
    (burst / ".credentials.json").write_text("burst-login")
    (burst / ".claude.json").write_text("burst-account")
    _link(tmp_path)
    assert (burst / ".credentials.json").read_text() == "burst-login"
    assert (burst / ".claude.json").read_text() == "burst-account"


def test_replaces_a_file_written_over_a_link(tmp_path):
    claude = _home(tmp_path)
    burst = tmp_path / ".claude-burst"
    burst.mkdir()
    (burst / "settings.json").write_text("written over the link")
    _link(tmp_path)
    assert (burst / "settings.json").is_symlink()
    assert (burst / "settings.json").read_text() == (claude / "settings.json").read_text()


def test_picks_up_new_entries_and_drops_dangling_links(tmp_path):
    claude = _home(tmp_path)
    _link(tmp_path)
    (claude / ".hidden").unlink()
    (claude / "plugins").mkdir()
    _link(tmp_path)
    assert sorted(p.name for p in (tmp_path / ".claude-burst").iterdir()) == ["..odd", "plugins", "projects", "settings.json"]


def test_leaves_a_dangling_link_it_did_not_make(tmp_path):
    _home(tmp_path)
    burst = tmp_path / ".claude-burst"
    burst.mkdir()
    (burst / "mine").symlink_to(tmp_path / "gone")
    _link(tmp_path)
    assert (burst / "mine").is_symlink()


def test_leaves_a_real_directory_alone_with_a_warning(tmp_path):
    _home(tmp_path)
    own = tmp_path / ".claude-burst" / "projects"
    own.mkdir(parents=True)
    (own / "session.jsonl").write_text("burst")
    result = _link(tmp_path)
    assert not own.is_symlink()
    assert (own / "session.jsonl").read_text() == "burst"
    assert "burst keeps its own copy" in result.stderr


def test_never_shares_an_account_file_found_in_the_main_config_dir(tmp_path):
    claude = _home(tmp_path)
    (claude / ".claude.json").write_text("main-account")
    burst = tmp_path / ".claude-burst"
    burst.mkdir()
    (burst / ".claude.json").write_text("burst-account")
    _link(tmp_path)
    assert not (burst / ".claude.json").is_symlink()
    assert (burst / ".claude.json").read_text() == "burst-account"


def test_ignores_claude_burst_dir_in_the_environment(tmp_path):
    _home(tmp_path)
    assert _link(tmp_path, CLAUDE_BURST_DIR=str(tmp_path / ".claude")).stdout.strip() == str(tmp_path / ".claude-burst")
    assert (tmp_path / ".claude" / "settings.json").read_text() == "settings.json"


def test_many_launches_at_once_all_succeed_and_never_touch_the_main_dir(tmp_path):
    claude = _home(tmp_path)
    for n in range(40):
        (claude / f"dir{n}").mkdir()
    before = sorted(p.relative_to(claude) for p in claude.rglob("*"))
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    for _ in range(3):
        procs = [subprocess.Popen([str(SCRIPT)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(16)]
        assert [p.wait() for p in procs] == [0] * 16
    assert sorted(p.relative_to(claude) for p in claude.rglob("*")) == before
    burst = tmp_path / ".claude-burst"
    assert all(p.is_symlink() for p in burst.iterdir())
    assert len(list(burst.iterdir())) == 44


def test_leaves_a_correct_link_alone(tmp_path):
    _home(tmp_path)
    _link(tmp_path)
    link = tmp_path / ".claude-burst" / "settings.json"
    before = link.lstat().st_ino
    _link(tmp_path)
    assert link.lstat().st_ino == before


def test_refuses_a_burst_dir_that_is_the_main_dir(tmp_path):
    _home(tmp_path)
    (tmp_path / ".claude-burst").symlink_to(tmp_path / ".claude")
    result = subprocess.run(
        [str(SCRIPT)], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "make it a separate directory" in result.stderr
    assert sorted(p.name for p in (tmp_path / ".claude").iterdir() if p.is_symlink()) == []
    assert (tmp_path / ".claude" / "settings.json").read_text() == "settings.json"


def test_works_without_a_claude_home(tmp_path):
    _link(tmp_path)
    assert list((tmp_path / ".claude-burst").iterdir()) == []
