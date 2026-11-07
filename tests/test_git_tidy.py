import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "zsh" / ".config" / "zsh" / "functions"
GITCONFIG = ROOT / "git" / ".gitconfig"

CONFIG = """[user]
\tname = Tidy Test
\temail = tidy@example.com
[commit]
\tgpgsign = false
[init]
\tdefaultBranch = main
[core]
\thooksPath = /dev/null
"""


def test_the_alias_runs_the_function_in_a_bare_zsh():
    alias = subprocess.run(
        ["git", "config", "-f", str(GITCONFIG), "--get", "alias.tidy"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert alias.startswith("!zsh -f")
    assert "autoload -Uz git-tidy" in alias
    assert '"$@"' in alias


class Repo:
    """A clone of a bare origin with one commit on main, and a git environment that ignores the real config."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        (self.home / ".config" / "zsh").mkdir(parents=True)
        (self.home / ".config" / "zsh" / "functions").symlink_to(FUNCTIONS)
        config = tmp_path / "gitconfig"
        config.write_text(CONFIG)
        self.env = {
            "PATH": os.environ["PATH"], "HOME": str(self.home), "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        }
        self.origin = tmp_path / "origin.git"
        self.work = tmp_path / "work"
        self.git("init", "--bare", str(self.origin), cwd=tmp_path)
        self.git("clone", "-q", str(self.origin), str(self.work), cwd=tmp_path)
        self.commit("base")
        self.git("push", "-q", "-u", "origin", "main")

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.work, env=self.env, capture_output=True, text=True, check=check,
        )

    def commit(self, name: str, cwd: Path | None = None) -> None:
        (cwd or self.work).joinpath(name).write_text(name)
        self.git("add", name, cwd=cwd)
        self.git("commit", "-q", "-m", name, cwd=cwd)

    def branch_with_commit(self, name: str) -> None:
        self.git("switch", "-q", "-c", name)
        self.commit(name)
        self.git("switch", "-q", "main")

    def merge(self, name: str, squash: bool = False) -> None:
        self.git("switch", "-q", "main")
        if squash:
            self.git("merge", "-q", "--squash", name)
            self.git("commit", "-q", "-m", f"squash {name}")
        else:
            self.git("merge", "-q", "--no-ff", "-m", f"merge {name}", name)
        self.git("push", "-q", "origin", "main")

    def branches(self) -> list[str]:
        out = self.git("for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
        return sorted(out.split())

    def tidy(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        script = f'fpath=("{FUNCTIONS}" $fpath); autoload -Uz git-tidy; git-tidy "$@"'
        return subprocess.run(
            ["zsh", "-fc", script, "git-tidy", *args], cwd=cwd or self.work, env=self.env,
            capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL,
        )


@pytest.fixture
def repo(tmp_path):
    if shutil.which("zsh") is None:
        pytest.skip("zsh not installed")
    return Repo(tmp_path)


def test_deletes_a_branch_merged_with_a_merge_commit(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat")
    result = repo.tidy("--yes")
    assert result.returncode == 0, result.stderr
    assert repo.branches() == ["main"]
    assert "Deleted branch feat" in result.stdout


def test_deletes_a_squash_merged_branch(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat", squash=True)
    result = repo.tidy("--yes")
    assert result.returncode == 0, result.stderr
    assert repo.branches() == ["main"]
    assert "Squash- or rebase-merged" in result.stdout


def test_deletes_a_rebase_merged_branch(repo):
    repo.branch_with_commit("feat")
    repo.git("switch", "-q", "main")
    repo.commit("other")
    repo.git("cherry-pick", "feat")
    repo.git("push", "-q", "origin", "main")
    assert repo.tidy("--yes").returncode == 0
    assert repo.branches() == ["main"]


def test_keeps_a_branch_with_unmerged_work(repo):
    repo.branch_with_commit("wip")
    result = repo.tidy("--yes")
    assert result.returncode == 0, result.stderr
    assert repo.branches() == ["main", "wip"]
    assert "Nothing to tidy" in result.stdout


def test_keeps_a_branch_that_was_just_created_at_the_base(repo):
    repo.git("branch", "fresh")
    repo.tidy("--yes")
    assert repo.branches() == ["fresh", "main"]


def test_keeps_the_branch_that_is_checked_out_even_when_merged(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat")
    repo.git("switch", "-q", "feat")
    repo.tidy("--yes")
    assert repo.branches() == ["feat", "main"]


def test_lists_a_branch_whose_upstream_is_gone_but_keeps_it(repo):
    repo.git("switch", "-q", "-c", "lost")
    repo.commit("lost")
    repo.git("push", "-q", "-u", "origin", "lost")
    repo.git("switch", "-q", "main")
    repo.git("push", "-q", "origin", "--delete", "lost")
    result = repo.tidy("--yes")
    assert repo.branches() == ["lost", "main"]
    assert "upstream is gone" in result.stdout


def test_removes_a_clean_worktree_with_its_merged_branch(repo):
    wt = repo.tmp / "wt-feat"
    repo.git("worktree", "add", "-q", str(wt), "-b", "feat")
    repo.commit("feat", cwd=wt)
    repo.merge("feat")
    result = repo.tidy("--yes")
    assert result.returncode == 0, result.stderr
    assert not wt.exists()
    assert repo.branches() == ["main"]


def test_keeps_a_worktree_with_uncommitted_changes_and_its_branch(repo):
    wt = repo.tmp / "wt-feat"
    repo.git("worktree", "add", "-q", str(wt), "-b", "feat")
    repo.commit("feat", cwd=wt)
    repo.merge("feat")
    (wt / "scratch").write_text("unsaved")
    result = repo.tidy("--yes")
    assert wt.exists()
    assert repo.branches() == ["feat", "main"]
    assert "uncommitted changes" in result.stdout


def test_keeps_a_locked_worktree_and_its_branch(repo):
    wt = repo.tmp / "wt-feat"
    repo.git("worktree", "add", "-q", str(wt), "-b", "feat")
    repo.commit("feat", cwd=wt)
    repo.merge("feat")
    repo.git("worktree", "lock", str(wt))
    result = repo.tidy("--yes")
    assert wt.exists()
    assert repo.branches() == ["feat", "main"]
    assert "locked" in result.stdout


def test_prunes_the_record_of_a_deleted_worktree_and_deletes_its_branch(repo):
    wt = repo.tmp / "wt-feat"
    repo.git("worktree", "add", "-q", str(wt), "-b", "feat")
    repo.commit("feat", cwd=wt)
    repo.merge("feat")
    shutil.rmtree(wt)
    result = repo.tidy("--yes")
    assert result.returncode == 0, result.stderr
    assert repo.branches() == ["main"]
    assert str(wt) not in repo.git("worktree", "list").stdout


def test_run_from_inside_a_linked_worktree_keeps_that_worktrees_branch(repo):
    wt = repo.tmp / "wt-feat"
    repo.git("worktree", "add", "-q", str(wt), "-b", "feat")
    repo.commit("feat", cwd=wt)
    repo.merge("feat")
    repo.tidy("--yes", cwd=wt)
    assert wt.exists()
    assert repo.branches() == ["feat", "main"]


def test_dry_run_lists_the_plan_and_changes_nothing(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat")
    result = repo.tidy("--dry-run")
    assert result.returncode == 0
    assert "  feat" in result.stdout
    assert "Dry run" in result.stdout
    assert repo.branches() == ["feat", "main"]


def test_refuses_to_change_anything_without_a_terminal_or_yes(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat")
    result = repo.tidy()
    assert result.returncode == 1
    assert "--yes" in result.stderr
    assert repo.branches() == ["feat", "main"]


def test_fetches_with_prune_before_looking(repo):
    repo.branch_with_commit("feat")
    repo.git("push", "-q", "-u", "origin", "feat")
    other = repo.tmp / "other"
    repo.git("clone", "-q", str(repo.origin), str(other), cwd=repo.tmp)
    repo.git("merge", "-q", "--no-ff", "-m", "merge feat", "origin/feat", cwd=other)
    repo.git("push", "-q", "origin", "main", cwd=other)
    assert repo.tidy("--yes").returncode == 0
    assert repo.branches() == ["main"]


def test_no_fetch_works_from_the_refs_already_here(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat")
    repo.git("remote", "set-url", "origin", str(repo.tmp / "gone.git"))
    result = repo.tidy("--yes", "--no-fetch")
    assert result.returncode == 0, result.stderr
    assert repo.branches() == ["main"]


def test_an_explicit_base_decides_what_counts_as_merged(repo):
    repo.branch_with_commit("feat")
    repo.git("switch", "-q", "-c", "release", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "m", "feat")
    repo.git("switch", "-q", "main")
    repo.tidy("--yes", "--base", "release")
    assert repo.branches() == ["main", "release"]


def test_an_unknown_base_is_an_error(repo):
    result = repo.tidy("--yes", "--base", "nowhere")
    assert result.returncode == 1
    assert "no base branch" in result.stderr


def test_rejects_unknown_arguments(repo):
    result = repo.tidy("--wat")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_outside_a_repository_it_says_so(tmp_path):
    outside = tmp_path / "plain"
    outside.mkdir()
    result = subprocess.run(
        ["zsh", "-fc", f'fpath=("{FUNCTIONS}" $fpath); autoload -Uz git-tidy; git-tidy --yes'],
        cwd=outside, env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GIT_CEILING_DIRECTORIES": str(tmp_path)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "not inside a git work tree" in result.stderr


def test_the_git_alias_runs_the_function_and_passes_arguments(repo):
    repo.branch_with_commit("feat")
    repo.merge("feat")
    alias = subprocess.run(
        ["git", "config", "-f", str(GITCONFIG), "--get", "alias.tidy"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    dry = repo.git("-c", f"alias.tidy={alias}", "tidy", "--dry-run")
    assert "  feat" in dry.stdout
    assert repo.branches() == ["feat", "main"]
    repo.git("-c", f"alias.tidy={alias}", "tidy", "--yes")
    assert repo.branches() == ["main"]
