import subprocess

from dotfiles_setup.log import Logger
from dotfiles_setup.update import pull_if_behind, pull_overlay_if_git


def _fake_run(responses):
    calls = []

    def run(argv, **_):
        calls.append(argv[3])
        code, out = responses.get(argv[3], (0, ""))
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="boom")

    return run, calls


def test_pulls_when_behind(tmp_path):
    run, calls = _fake_run({"rev-list": (0, "2\n")})
    assert pull_if_behind(tmp_path, Logger(dry_run=False), run=run) is True
    assert calls == ["fetch", "rev-list", "pull"]


def test_skips_pull_when_up_to_date(tmp_path):
    run, calls = _fake_run({"rev-list": (0, "0\n")})
    assert pull_if_behind(tmp_path, Logger(dry_run=False), run=run) is False
    assert "pull" not in calls


def test_skips_pull_without_upstream(tmp_path):
    run, calls = _fake_run({"rev-list": (128, "")})
    assert pull_if_behind(tmp_path, Logger(dry_run=False), run=run) is False
    assert "pull" not in calls


def test_dry_run_does_not_pull(tmp_path):
    run, calls = _fake_run({"rev-list": (0, "1\n")})
    assert pull_if_behind(tmp_path, Logger(dry_run=True), run=run) is False
    assert "pull" not in calls


def test_fetch_failure_is_not_fatal(tmp_path):
    run, calls = _fake_run({"fetch": (1, "")})
    assert pull_if_behind(tmp_path, Logger(dry_run=False), run=run) is False
    assert calls == ["fetch"]


def test_failed_fast_forward_returns_false(tmp_path):
    run, _ = _fake_run({"rev-list": (0, "1\n"), "pull": (1, "")})
    assert pull_if_behind(tmp_path, Logger(dry_run=False), run=run) is False


def test_missing_git_is_not_fatal(tmp_path):
    def run(argv, **_):
        raise FileNotFoundError("git")

    assert pull_if_behind(tmp_path, Logger(dry_run=False), run=run) is False


def test_missing_upstream_warning_names_the_branch(tmp_path, capsys):
    run, _ = _fake_run({"rev-list": (128, ""), "symbolic-ref": (0, "feature/x\n")})
    pull_if_behind(tmp_path, Logger(dry_run=False), run=run)
    out = capsys.readouterr().out
    assert "branch 'feature/x' has no upstream" in out
    assert "git push -u origin feature/x" in out


def test_detached_head_warning_says_so(tmp_path, capsys):
    run, _ = _fake_run({"rev-list": (128, ""), "symbolic-ref": (1, "")})
    pull_if_behind(tmp_path, Logger(dry_run=False), run=run)
    assert "HEAD is detached" in capsys.readouterr().out


def test_git_calls_ignore_repo_location_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/elsewhere/.git")
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i key")
    envs = []

    def run(argv, **kwargs):
        envs.append(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, stdout="0\n", stderr="")

    pull_if_behind(tmp_path, Logger(dry_run=False), run=run)
    assert envs
    assert all("GIT_DIR" not in e for e in envs)
    assert all(e["GIT_SSH_COMMAND"] == "ssh -i key" for e in envs)


def test_overlay_pull_skips_missing_overlay():
    run, calls = _fake_run({})
    assert pull_overlay_if_git(None, Logger(dry_run=False), run=run) is False
    assert calls == []


def test_overlay_pull_skips_non_git_directory(tmp_path):
    run, calls = _fake_run({})
    assert pull_overlay_if_git(tmp_path, Logger(dry_run=False), run=run) is False
    assert calls == []


def test_overlay_pull_pulls_git_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    run, calls = _fake_run({"rev-list": (0, "1\n")})
    assert pull_overlay_if_git(tmp_path, Logger(dry_run=False), run=run) is True
    assert calls == ["fetch", "rev-list", "pull"]


def test_overlay_pull_warning_names_private_repo(tmp_path, capsys):
    (tmp_path / ".git").mkdir()
    run, _ = _fake_run({"rev-list": (128, "")})
    pull_overlay_if_git(tmp_path, Logger(dry_run=False), run=run)
    assert "Skipping dotfiles-overlay update" in capsys.readouterr().out


def test_missing_upstream_command_quotes_the_branch(tmp_path, capsys):
    run, _ = _fake_run({"rev-list": (128, ""), "symbolic-ref": (0, "feat;id\n")})
    pull_if_behind(tmp_path, Logger(dry_run=False), run=run)
    assert "git push -u origin 'feat;id'" in capsys.readouterr().out


def _restart(monkeypatch, pulled, argv, marker=None):
    from dotfiles_setup import update

    monkeypatch.delenv(update.RESTARTED_VAR, raising=False)
    if marker:
        monkeypatch.setenv(update.RESTARTED_VAR, marker)
    seen = []
    update.restart_if_updated(pulled, Logger(dry_run=False), argv=argv, execv=lambda *a: seen.append(a))
    return seen


def test_restarts_dfctl_after_pull(monkeypatch):
    seen = _restart(monkeypatch, True, ["/x/bin/dfctl", "apply", "--yes"])
    assert len(seen) == 1 and seen[0][1][1:] == ["/x/bin/dfctl", "apply", "--yes"]


def test_no_restart_without_pull(monkeypatch):
    assert _restart(monkeypatch, False, ["/x/bin/dfctl", "apply"]) == []


def test_no_restart_twice(monkeypatch):
    assert _restart(monkeypatch, True, ["/x/bin/dfctl", "apply"], marker="1") == []


def test_no_restart_outside_dfctl(monkeypatch):
    assert _restart(monkeypatch, True, ["/usr/bin/pytest"]) == []
