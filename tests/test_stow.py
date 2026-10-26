from types import SimpleNamespace

import pytest
from dotfiles_setup import stow, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


class Stower:
    """Stands in for stow, git and everything else: simulates one conflict and records every call."""

    def __init__(self, conflict=".rc", stow_rc=0, git_rc=0):
        self.calls = []
        self.conflict = conflict
        self.stow_rc = stow_rc
        self.git_rc = git_rc

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("cwd")))
        if argv[0] == "git":
            return SimpleNamespace(returncode=self.git_rc, stdout="", stderr="")
        if "--simulate" in argv:
            line = f"  * existing target is neither a link nor a directory: {self.conflict}"
            return SimpleNamespace(returncode=0, stdout="", stderr=line)
        return SimpleNamespace(returncode=self.stow_rc, stdout="", stderr="stow failed" if self.stow_rc else "")

    def stow_calls(self):
        return [argv[1:] for argv, _ in self.calls if argv[0] == "stow" and "--simulate" not in argv]


@pytest.fixture
def world(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    return SimpleNamespace(tmp=tmp_path, home=home, repo=repo)


def plan_for(world, runner=None, force=True, private=None, dry_run=False, backup_root=None):
    runner = runner or Stower()
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), world.home, run=runner)
    return stow.StowPlan(
        t, world.repo, private, force, backup_root or world.tmp / "backups", "T1",
        RollbackLog(world.tmp / "rollback.log"),
    ), runner


def backups(world, name):
    return [p for p in (world.tmp / "backups").glob(f"T1.*/{name}")]


def test_force_backs_up_the_conflicting_file_and_removes_the_staging_dir(world):
    plan, _ = plan_for(world)
    (world.home / ".rc").write_text("original")
    assert stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert backups(world, ".rc")[0].read_text() == "original"
    assert not list(world.home.glob(".stow-backup.*"))


def test_two_backups_in_the_same_second_are_both_kept(world):
    plan, _ = plan_for(world)
    for content in ("first", "second"):
        (world.home / ".rc").write_text(content)
        stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert sorted(p.read_text() for p in backups(world, ".rc")) == ["first", "second"]


def test_a_stow_failure_fails_but_still_backs_the_file_up(world):
    plan, _ = plan_for(world, Stower(stow_rc=1))
    (world.home / ".rc").write_text("original")
    assert not stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert backups(world, ".rc")[0].read_text() == "original"


def test_a_failed_backup_fails_and_keeps_the_originals_staged(world):
    blocker = world.tmp / "blocker"
    blocker.write_text("")
    plan, _ = plan_for(world, backup_root=blocker / "backups")
    (world.home / ".rc").write_text("original")
    assert not stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert next(world.home.glob(".stow-backup.*/.rc")).read_text() == "original"


def test_a_file_reached_through_a_symlink_outside_home_is_never_moved(world):
    external = world.tmp / "external"
    external.mkdir()
    (external / "f").write_text("external")
    (world.home / "link").symlink_to(external)
    plan, _ = plan_for(world, Stower(conflict="link/f"))
    stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert (external / "f").read_text() == "external"


@pytest.mark.parametrize("conflict", ["../escape", "/etc/passwd", "a/../../b"])
def test_suspicious_conflict_paths_are_never_backed_up(world, conflict):
    plan, _ = plan_for(world, Stower(conflict=conflict))
    stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert not list((world.tmp / "backups").glob("**/*"))


def test_without_force_nothing_is_staged_or_simulated(world):
    plan, runner = plan_for(world, force=False)
    (world.home / ".rc").write_text("original")
    assert stow.stow_with_backup(plan, [f"--target={world.home}", "pkg"], world.repo)
    assert (world.home / ".rc").read_text() == "original"
    assert all("--simulate" not in argv for argv, _ in runner.calls)


def test_stow_runs_in_the_package_root(world):
    plan, runner = plan_for(world, force=False)
    stow.stow_with_backup(plan, ["pkg"], world.repo)
    assert runner.calls[0][1] == world.repo


def make_repo(world):
    for pkg, files in {"pkgA": [".rca"], "pkgB": [".rcb"], "pkgC": [".cfg/f"]}.items():
        for name in files:
            path = world.repo / pkg / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(pkg)


def test_only_packages_not_already_linked_are_reported(world):
    make_repo(world)
    (world.home / ".rca").symlink_to(world.repo / "pkgA/.rca")
    (world.home / ".cfg").symlink_to(world.repo / "pkgC/.cfg")
    (world.home / ".rcb").write_text("other")
    assert stow.pkgs_not_yet_linked(world.repo, world.home, ["pkgA", "pkgB", "pkgC"]) == ["pkgB"]


def test_an_empty_package_counts_as_not_linked(world):
    (world.repo / "empty").mkdir()
    assert stow.pkgs_not_yet_linked(world.repo, world.home, ["empty"]) == ["empty"]


def test_regex_escape_protects_literal_dots_and_brackets():
    assert stow.stow_regex_escape(".claude/CLAUDE.md") == r"\.claude/CLAUDE\.md"
    assert stow.stow_regex_escape("a[1](b)+c") == r"a\[1]\(b\)\+c"


def write_packages(path, *names):
    path.write_text("# comment\n\n" + "\n".join(names) + "\n")


def test_private_files_that_override_public_ones_are_ignored_by_the_public_stow(world):
    private = world.tmp / "private"
    (private / "claude/.claude").mkdir(parents=True)
    (private / "claude/.claude/CLAUDE.md").write_text("private")
    (private / "claude/.claude/extra.md").write_text("only private")
    write_packages(private / ".stow-packages", "claude")
    (world.repo / "claude/.claude").mkdir(parents=True)
    (world.repo / "claude/.claude/CLAUDE.md").write_text("public")
    plan, _ = plan_for(world, private=private)
    assert stow.private_override_ignores(plan) == [r"--ignore=\.claude/CLAUDE\.md"]


def test_the_common_stow_splits_folded_and_unfolded_packages_and_tracks_new_ones(world):
    make_repo(world)
    (world.repo / "gradle/.gradle").mkdir(parents=True)
    (world.repo / "gradle/.gradle/f").write_text("g")
    write_packages(world.repo / ".stow-packages", "pkgA", "gradle")
    plan, runner = plan_for(world, force=False)
    assert stow.stow_common_to_home(plan, ["--ignore=x"])
    unfolded, folded = runner.stow_calls()
    assert unfolded[:2] == ["--restow", "--no-folding"]
    assert unfolded[-1] == "pkgA"
    assert "--no-folding" not in folded
    assert folded[-1] == "gradle"
    assert "--ignore=x" in unfolded
    assert plan.changes.entries() == ["STOW_HOME:pkgA", "STOW_HOME:gradle"]


def test_a_missing_stow_packages_file_is_skipped(world):
    plan, runner = plan_for(world)
    assert stow.stow_common_to_home(plan, [])
    assert runner.calls == []


def test_an_unfolded_package_over_the_file_limit_is_refused(world, monkeypatch):
    monkeypatch.setattr(stow, "UNFOLD_LIMIT", 2)
    for n in range(3):
        path = world.repo / "big" / f"f{n}"
        path.parent.mkdir(exist_ok=True)
        path.write_text("")
    write_packages(world.repo / ".stow-packages", "big")
    plan, runner = plan_for(world, force=False)
    assert not stow.stow_common_to_home(plan, [])
    assert runner.calls == []


def test_a_dry_run_stows_and_tracks_nothing(world):
    make_repo(world)
    write_packages(world.repo / ".stow-packages", "pkgA")
    plan, runner = plan_for(world, dry_run=True)
    assert stow.configure_dotfiles(plan)
    assert runner.calls == []
    assert plan.changes.entries() == []


def test_the_private_overlay_replaces_a_public_symlink_and_tracks_its_packages(world):
    private = world.tmp / "private"
    (private / "claude/.claude").mkdir(parents=True)
    (private / "claude/.claude/CLAUDE.md").write_text("private")
    write_packages(private / ".stow-packages", "claude")
    (world.repo / "claude/.claude").mkdir(parents=True)
    public = world.repo / "claude/.claude/CLAUDE.md"
    public.write_text("public")
    target = world.home / ".claude/CLAUDE.md"
    target.parent.mkdir()
    target.symlink_to(public)
    plan, runner = plan_for(world, private=private, force=False)
    assert stow.stow_private_to_home(plan)
    assert not target.is_symlink()
    assert runner.stow_calls() == [["--restow", "--no-folding", f"--target={world.home}", "--verbose=1", "claude"]]
    assert runner.calls[0][1] == private
    assert plan.changes.entries() == ["STOW_PRIVATE:claude"]


def test_a_non_repo_symlink_at_a_private_path_is_left_alone(world):
    private = world.tmp / "private"
    (private / "local/.local").mkdir(parents=True)
    (private / "local/.local/tool").write_text("private")
    write_packages(private / ".stow-packages", "local")
    elsewhere = world.tmp / "elsewhere"
    elsewhere.write_text("")
    target = world.home / ".local/tool"
    target.parent.mkdir()
    target.symlink_to(elsewhere)
    plan, _ = plan_for(world, private=private, force=False)
    stow.stow_private_to_home(plan)
    assert target.is_symlink()


def test_no_private_root_means_no_private_stow(world):
    plan, runner = plan_for(world)
    assert stow.stow_private_to_home(plan)
    assert runner.calls == []


def test_a_failed_common_stow_stops_the_dotfiles_step(world):
    make_repo(world)
    write_packages(world.repo / ".stow-packages", "pkgA")
    plan, runner = plan_for(world, Stower(stow_rc=1), force=False)
    assert not stow.configure_dotfiles(plan)
    assert not any(argv[0] == "git" for argv, _ in runner.calls)
    assert plan.changes.entries() == []


def test_git_hooks_path_is_set_after_a_successful_stow(world):
    make_repo(world)
    write_packages(world.repo / ".stow-packages", "pkgA")
    plan, runner = plan_for(world, force=False)
    assert stow.configure_dotfiles(plan)
    assert (["git", "config", "--local", "core.hooksPath", ".githooks"], world.repo) in runner.calls


def test_a_failed_git_config_fails_the_step(world):
    plan, _ = plan_for(world, Stower(git_rc=1), force=False)
    assert not stow.configure_git_hooks(plan)
