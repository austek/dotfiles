from dotfiles_setup.private import clone_overlay


def test_clone_overlay_runs_git_clone_with_repo_and_dest(tmp_path):
    calls = []

    def fake_run(argv):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Result()

    dest = tmp_path / "dotfiles-private"
    result = clone_overlay("git@github.com:you/dotfiles-private.git", dest, run=fake_run)
    assert result.succeeded
    assert calls == [["git", "clone", "git@github.com:you/dotfiles-private.git", str(dest)]]


def test_clone_overlay_refuses_to_overwrite_existing_dest(tmp_path):
    dest = tmp_path / "dotfiles-private"
    dest.mkdir()

    def unexpected_run(argv):
        raise AssertionError("git clone should not run when dest already exists")

    result = clone_overlay("git@github.com:you/dotfiles-private.git", dest, run=unexpected_run)
    assert not result.succeeded
    assert "already exists" in result.stdout


def test_clone_overlay_reports_git_failure(tmp_path):
    def failing_run(argv):
        class _Result:
            returncode = 128
            stdout = ""
            stderr = "fatal: repository not found"
        return _Result()

    dest = tmp_path / "dotfiles-private"
    result = clone_overlay("git@github.com:you/dotfiles-private.git", dest, run=failing_run)
    assert not result.succeeded
    assert result.returncode == 128
    assert "not found" in result.stdout
