import subprocess

import coderabbit_full_audit as cra
import pytest


class FakeRun:
    """Matches subprocess.run's signature; dispatches by command prefix.

    `responses` maps a command-prefix tuple to either a canned
    CompletedProcess or a callable(cmd, cwd) -> CompletedProcess, for
    cases where successive calls to the same prefix must answer
    differently (e.g. `git rev-parse --abbrev-ref HEAD` before/after a
    branch switch). Unmatched commands default to a quiet success.
    """

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, cmd, cwd=None, **kwargs):
        self.calls.append((tuple(cmd), cwd))
        for prefix, resp in self.responses.items():
            if tuple(cmd)[: len(prefix)] == prefix:
                return resp(cmd, cwd) if callable(resp) else resp
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def ok(stdout="", returncode=0):
    return lambda cmd, cwd: subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def sequence(values):
    it = iter(values)
    return lambda cmd, cwd: subprocess.CompletedProcess(cmd, 0, stdout=next(it), stderr="")


@pytest.fixture(autouse=True)
def _isolated_export(tmp_path, monkeypatch):
    monkeypatch.setattr(cra, "EXPORT_FILE", tmp_path / "coderabbit_audit.md")


def test_scope_flags_are_mutually_exclusive():
    parser = cra.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--uncommitted", "--path", "src"])


def test_limit_rejects_non_positive_values():
    parser = cra.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--limit", "0"])


def test_clamp_limit_clamps_above_free_tier_ceiling(capsys):
    assert cra.clamp_limit(500) == cra.FREE_TIER_CEILING
    assert "clamping" in capsys.readouterr().err


def test_clamp_limit_passes_through_within_ceiling():
    assert cra.clamp_limit(50) == 50


def test_parse_negated_filters_extracts_bang_patterns_and_stops_at_next_key():
    yaml_text = """\
reviews:
  path_filters:
    - "!vendor/**"
    - "!*.min.js"
    - "src/**"
  path_instructions:
    - path: "**"
      instructions: "be nice"
"""
    assert cra._parse_negated_filters(yaml_text) == ["vendor/**", "*.min.js"]


def test_uncommitted_files_parses_porcelain_including_renames():
    run = FakeRun({("git", "status", "--porcelain"): ok(" M changed.py\n?? new.py\nR  old.py -> new2.py\n")})
    assert cra.uncommitted_files(run) == ["changed.py", "new.py", "new2.py"]


def test_chunk_splits_into_batches_of_size():
    assert cra.chunk(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]


def test_main_full_repo_default_scope_runs_single_batch(tmp_path):
    responses = {
        ("git", "rev-parse", "--show-toplevel"): ok(str(tmp_path / "repo") + "\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("main\n"),
        ("git", "cat-file", "-e"): ok(returncode=0),
        ("git", "ls-tree", "-r", "--name-only", "main", "--", "."): ok("a.py\nb.py\n"),
        ("git", "show", "main:.coderabbit.yaml"): ok(returncode=1),
        ("coderabbit", "review"): ok("REVIEW OUTPUT\n"),
    }
    run = FakeRun(responses)
    assert cra.main([], run=run) == 0
    assert cra.EXPORT_FILE.read_text() == "REVIEW OUTPUT\n"
    assert any(c[0][:2] == ("git", "worktree") and c[0][2] == "add" for c in run.calls)
    review_calls = [c for c in run.calls if c[0][:2] == ("coderabbit", "review")]
    assert review_calls == [(("coderabbit", "review", "--base", "audit-base-full-repo", "--agent"), review_calls[0][1])]


def test_main_missing_coderabbit_yaml_errors(tmp_path, capsys):
    responses = {
        ("git", "rev-parse", "--show-toplevel"): ok(str(tmp_path / "repo") + "\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("main\n"),
        ("git", "cat-file", "-e"): ok(returncode=1),
    }
    run = FakeRun(responses)
    assert cra.main([], run=run) == 1
    assert ".coderabbit.yaml not found" in capsys.readouterr().err


def test_main_uncommitted_within_limit_uses_simple_review(tmp_path):
    responses = {
        ("git", "rev-parse", "--show-toplevel"): ok(str(tmp_path / "repo") + "\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("main\n"),
        ("git", "status", "--porcelain"): ok(" M a.py\n"),
        ("coderabbit", "review"): ok("SIMPLE REVIEW\n"),
    }
    run = FakeRun(responses)
    assert cra.main(["--uncommitted"], run=run) == 0
    assert cra.EXPORT_FILE.read_text() == "SIMPLE REVIEW\n"
    assert not any(c[0][:2] == ("git", "worktree") for c in run.calls)
    assert ("coderabbit", "review", "--uncommitted", "--agent") in [c[0] for c in run.calls]


def test_main_uncommitted_over_limit_batches_via_stash_create(tmp_path):
    responses = {
        ("git", "rev-parse", "--show-toplevel"): ok(str(tmp_path / "repo") + "\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("main\n"),
        ("git", "status", "--porcelain"): ok(" M a.py\n M b.py\n"),
        ("git", "stash", "create"): ok("deadbeef\n"),
        ("coderabbit", "review"): sequence(["REVIEW1\n", "REVIEW2\n"]),
    }
    run = FakeRun(responses)
    assert cra.main(["--uncommitted", "--limit", "1"], run=run) == 0
    content = cra.EXPORT_FILE.read_text()
    assert "Batch 1/2" in content and "REVIEW1" in content
    assert "Batch 2/2" in content and "REVIEW2" in content
    assert any(c[0][:2] == ("git", "worktree") and c[0][2] == "add" for c in run.calls)


def test_main_pr_uses_existing_review_when_present(tmp_path):
    responses = {
        ("git", "rev-parse", "--show-toplevel"): ok(str(tmp_path / "repo") + "\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("main\n"),
        ("coderabbit", "pullrequest"): ok("EXISTING REVIEW\n"),
    }
    run = FakeRun(responses)
    assert cra.main(["--pr", "42"], run=run) == 0
    assert cra.EXPORT_FILE.read_text() == "EXISTING REVIEW\n"
    assert not any(c[0][:2] == ("gh", "pr") for c in run.calls)


def test_main_pr_falls_back_to_live_diff_and_restores_branch(tmp_path):
    responses = {
        ("git", "rev-parse", "--show-toplevel"): ok(str(tmp_path / "repo") + "\n"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): sequence(["main\n", "main\n", "pr-branch\n"]),
        ("coderabbit", "pullrequest"): ok(returncode=1),
        ("gh", "pr", "checkout"): ok(),
        ("gh", "pr", "view"): ok('{"baseRefName": "main"}\n'),
        ("gh", "pr", "diff"): ok("x.py\ny.py\n"),
        ("coderabbit", "review"): ok("PR REVIEW\n"),
    }
    run = FakeRun(responses)
    assert cra.main(["--pr", "42"], run=run) == 0
    assert cra.EXPORT_FILE.read_text() == "PR REVIEW\n"
    assert run.calls[-1][0] == ("git", "checkout", "main")


def _init_git_repo(path, monkeypatch):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    (path / "hello.py").write_text("print('hi')\n")
    (path / ".coderabbit.yaml").write_text("reviews:\n  path_filters: []\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "initial"], check=True)
    monkeypatch.chdir(path)


def test_main_full_repo_real_git_worktree_lifecycle(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _init_git_repo(repo, monkeypatch)

    def run(cmd, cwd=None, **kwargs):
        if cmd[0] == "coderabbit":
            return subprocess.CompletedProcess(cmd, 0, stdout="INTEGRATION REVIEW\n", stderr="")
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)

    assert cra.main([], run=run) == 0
    assert cra.EXPORT_FILE.read_text() == "INTEGRATION REVIEW\n"
    assert not (tmp_path / "cr-audit-scratch-full-repo").exists()
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list"], capture_output=True, text=True, check=False
    ).stdout
    assert "audit-base-full-repo" not in branches
