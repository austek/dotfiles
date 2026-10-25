"""CodeRabbit audit runner behind the `coderabbitFullAudit` command.

Mirrors the five review scopes the `/coderabbit-audit` Claude command resolves
(uncommitted changes, a path, a PR, a branch, or the full repo) and keeps every
`coderabbit review` call under CodeRabbit's free-tier file-count ceiling (100) by
splitting an over-limit scope into multiple review calls, each built from a
scratch git worktree so the extra calls never touch the caller's working tree.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
Sleeper = Callable[[float], None]

FREE_TIER_CEILING = 100
RATE_LIMIT_MARGIN_SECONDS = 60
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 3600
MAX_RATE_LIMIT_WAITS = 6
_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
EXPORT_FILE = Path.home() / ".claude" / "scratches" / "handoff" / "coderabbit_audit.md"

EXAMPLES = """\
Examples:
  coderabbitFullAudit
  coderabbitFullAudit --path addon/globalPlugins
  coderabbitFullAudit --uncommitted
  coderabbitFullAudit --branch main
  coderabbitFullAudit --pr 482
  coderabbitFullAudit --path addon --limit 75
"""


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


def _not_option(value: str) -> str:
    if value.startswith("-"):
        raise argparse.ArgumentTypeError("must not start with '-'")
    return value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coderabbitFullAudit",
        description=(
            "Run a CodeRabbit review scoped to uncommitted changes, a path, a PR,\n"
            "a branch, or the full repo (default) -- batching into multiple review\n"
            "calls when the scope has more files than CodeRabbit's free-tier\n"
            "ceiling allows in one call."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_scope_args(parser)
    _add_limit_arg(parser)
    return parser


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--uncommitted", action="store_true", help="review uncommitted working-tree changes"
    )
    scope.add_argument(
        "--path", metavar="PATH", type=_not_option, help="full-content audit of PATH (not just its diff)"
    )
    scope.add_argument("--pr", metavar="NUM|URL", type=_not_option, help="review a pull request")
    scope.add_argument("--branch", metavar="NAME", type=_not_option, help="review the diff against NAME")


def _add_limit_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=FREE_TIER_CEILING,
        metavar="N",
        help=(
            "max files per review call (default: %(default)s; values above the "
            f"free-tier ceiling of {FREE_TIER_CEILING} are clamped down to it)"
        ),
    )


def clamp_limit(limit: int) -> int:
    if limit > FREE_TIER_CEILING:
        print(
            f"coderabbitFullAudit: --limit {limit} exceeds the free-tier ceiling of "
            f"{FREE_TIER_CEILING}; clamping to {FREE_TIER_CEILING}.",
            file=sys.stderr,
        )
        return FREE_TIER_CEILING
    return limit


def _rate_limit_event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    is_limit = isinstance(event, dict) and event.get("errorType") == "rate_limit"
    return event if is_limit else None


def rate_limit_wait_seconds(output: str) -> int | None:
    """Seconds to wait if `output` holds a CodeRabbit rate_limit error event, else None."""
    for line in output.splitlines():
        event = _rate_limit_event(line)
        if event is not None:
            wait = (event.get("metadata") or {}).get("waitTime", "")
            return _parse_wait(wait) + RATE_LIMIT_MARGIN_SECONDS
    return None


def _parse_wait(text: str) -> int:
    parts = re.findall(r"(\d+)\s*(second|minute|hour)", str(text))
    if not parts:
        return DEFAULT_RATE_LIMIT_WAIT_SECONDS
    return sum(int(n) * _UNIT_SECONDS[unit] for n, unit in parts)


def _announce_wait(wait: int, attempt: int) -> None:
    print(
        f"coderabbitFullAudit: rate limited; waiting {wait // 60} min before retrying "
        f"({attempt + 1}/{MAX_RATE_LIMIT_WAITS}).",
        file=sys.stderr,
    )


def review_waiting_for_limit(
    run: Runner, cmd: list[str], cwd: Path | None = None, sleep: Sleeper = time.sleep
) -> subprocess.CompletedProcess[str]:
    """Run a coderabbit command, sleeping out rate limits until the window reopens."""
    for attempt in range(MAX_RATE_LIMIT_WAITS + 1):
        result = run(cmd, cwd=cwd, capture_output=True, text=True)
        wait = rate_limit_wait_seconds(result.stdout or "")
        if wait is None or attempt == MAX_RATE_LIMIT_WAITS:
            return result
        _announce_wait(wait, attempt)
        sleep(wait)
    return result


def chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "scope"


def _git(
    run: Runner,
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    extra = {"env": env} if env else {}
    result = run(["git", *args], cwd=cwd, capture_output=True, text=True, **extra)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def current_branch(run: Runner, cwd: Path | None = None) -> str:
    return _git(run, "rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).stdout.strip()


def coderabbit_yaml_exists(run: Runner, branch: str, cwd: Path | None = None) -> bool:
    result = run(
        ["git", "cat-file", "-e", f"{branch}:.coderabbit.yaml"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def negated_path_filters(run: Runner, branch: str, cwd: Path | None = None) -> list[str]:
    result = run(["git", "show", f"{branch}:.coderabbit.yaml"], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return _parse_negated_filters(result.stdout)


def _parse_negated_filters(yaml_text: str) -> list[str]:
    lines = [line.strip() for line in yaml_text.splitlines()]
    after_header = itertools.dropwhile(lambda s: not re.match(r"^path_filters\s*:", s), lines)
    body = itertools.takewhile(lambda s: not re.match(r"^[A-Za-z_]+\s*:", s), list(after_header)[1:])
    matches = (re.search(r"""["']!([^"']+)["']""", s) for s in body)
    return [m.group(1) for m in matches if m]


def repo_files(
    run: Runner, branch: str, scope_path: str | None = None, cwd: Path | None = None
) -> list[str]:
    pathspec = [scope_path] if scope_path else ["."]
    result = _git(run, "ls-tree", "-r", "--name-only", "-z", branch, "--", *pathspec, cwd=cwd)
    files = _nul_split(result.stdout)
    if scope_path and ".coderabbit.yaml" not in files and coderabbit_yaml_exists(run, branch, cwd=cwd):
        files.append(".coderabbit.yaml")
    excluded: set[str] = set()
    for pattern in negated_path_filters(run, branch, cwd=cwd):
        matched = _git(
            run, "ls-tree", "-r", "--name-only", "-z", branch, "--", f":(glob){pattern}", cwd=cwd, check=False
        )
        excluded.update(_nul_split(matched.stdout))
    return [f for f in files if f not in excluded]


def _nul_split(text: str) -> list[str]:
    return [f for f in text.split("\0") if f]


def _porcelain_paths(entries: list[str]) -> list[str]:
    paths, skip_next = [], False
    for entry in entries:
        if skip_next:
            skip_next = False
            continue
        paths.append(entry[3:])
        skip_next = entry[0] in "RC"
    return paths


def uncommitted_files(run: Runner, cwd: Path | None = None) -> list[str]:
    result = _git(run, "status", "--porcelain", "-z", cwd=cwd)
    return _porcelain_paths(_nul_split(result.stdout))


def branch_diff_files(run: Runner, target_branch: str, cwd: Path | None = None) -> list[str]:
    result = _git(run, "diff", "--name-only", "-z", "--no-renames", f"{target_branch}...HEAD", cwd=cwd)
    return _nul_split(result.stdout)


def pr_diff_files(run: Runner, pr: str, cwd: Path | None = None) -> list[str]:
    result = run(["gh", "pr", "diff", pr, "--name-only"], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh pr diff {pr} --name-only failed: {result.stderr.strip()}")
    return [f for f in result.stdout.splitlines() if f]


def _pr_base_ref(run: Runner, pr: str, cwd: Path | None = None) -> str:
    result = run(
        ["gh", "pr", "view", pr, "--json", "baseRefName"], cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh pr view {pr} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)["baseRefName"]


def _write_export(content: str) -> None:
    EXPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_FILE.write_text(content)


def _append_export(content: str) -> None:
    EXPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EXPORT_FILE.open("a") as fh:
        fh.write(content)


def _run_simple(run: Runner, cmd: list[str], cwd: Path | None = None) -> int:
    result = review_waiting_for_limit(run, cmd, cwd=cwd)
    _write_export(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def _setup_baseline(
    run: Runner, worktree_dir: Path, base_branch: str, baseline_mode: str, base_ref: str | None
) -> None:
    if baseline_mode == "orphan":
        _git(run, "checkout", "--orphan", base_branch, cwd=worktree_dir)
        _git(run, "rm", "-rf", ".", cwd=worktree_dir, check=False)
        _git(run, "commit", "--allow-empty", "-m", "empty initial commit", cwd=worktree_dir)
    else:
        _git(run, "checkout", "-b", base_branch, base_ref, cwd=worktree_dir)


def _stage_batch(run: Runner, worktree_dir: Path, target_ref: str, batch_files: list[str]) -> None:
    listed = _git(run, "ls-tree", "-r", "--name-only", "-z", target_ref, "--", *batch_files, cwd=worktree_dir)
    present = set(_nul_split(listed.stdout))
    if present:
        _git(run, "checkout", target_ref, "--", *sorted(present), cwd=worktree_dir)
    deleted = [f for f in batch_files if f not in present]
    if deleted:
        _git(run, "rm", "-q", "--ignore-unmatch", "--", *deleted, cwd=worktree_dir)
    _git(run, "add", ".", cwd=worktree_dir)


@dataclass(frozen=True)
class ScopedAudit:
    repo_root: Path
    slug: str
    baseline_mode: str
    base_ref: str | None
    target_ref: str
    files: list[str]
    limit: int

    @property
    def base_branch(self) -> str:
        return f"audit-base-{self.slug}"

    @property
    def worktree_dir(self) -> Path:
        return self.repo_root.parent / f"cr-audit-scratch-{self.slug}"


def _review_batch(
    run: Runner, audit: ScopedAudit, files: list[str], num: int, total: int
) -> subprocess.CompletedProcess[str]:
    wt, base = audit.worktree_dir, audit.base_branch
    code_branch = f"{base}-code-{num}"
    _git(run, "checkout", "-b", code_branch, base, cwd=wt)
    try:
        _stage_batch(run, wt, audit.target_ref, files)
        _git(run, "commit", "-m", f"batch {num}/{total} snapshot for audit", cwd=wt)
        return review_waiting_for_limit(run, ["coderabbit", "review", "--base", base, "--agent"], cwd=wt)
    finally:
        _git(run, "checkout", "--force", base, cwd=wt, check=False)
        _git(run, "branch", "-D", code_branch, cwd=wt, check=False)


def _run_one_batch(run: Runner, audit: ScopedAudit, files: list[str], num: int, total: int) -> int:
    result = _review_batch(run, audit, files, num, total)
    header = f"\n## Batch {num}/{total} ({len(files)} file(s))\n\n" if total > 1 else ""
    _append_export(header + result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def _run_batches(run: Runner, audit: ScopedAudit) -> int:
    batches = chunk(audit.files, audit.limit)
    codes = []
    for i, batch in enumerate(batches, start=1):
        print(f"--- batch {i}/{len(batches)} ({len(batch)} file(s)) ---")
        codes.append(_run_one_batch(run, audit, batch, i, len(batches)))
    return next((c for c in codes if c), 0)


def _remove_scratch(run: Runner, audit: ScopedAudit) -> None:
    root = audit.repo_root
    _git(run, "worktree", "remove", "--force", str(audit.worktree_dir), cwd=root, check=False)
    _git(run, "branch", "-D", audit.base_branch, cwd=root, check=False)
    _git(run, "worktree", "prune", cwd=root, check=False)


def _run_scoped(run: Runner, audit: ScopedAudit) -> int:
    _git(run, "worktree", "add", "--detach", str(audit.worktree_dir), cwd=audit.repo_root)
    try:
        _setup_baseline(run, audit.worktree_dir, audit.base_branch, audit.baseline_mode, audit.base_ref)
        _write_export("")
        return _run_batches(run, audit)
    finally:
        _remove_scratch(run, audit)


def _content_scope_files(run: Runner, repo_root: Path, branch: str, scope_path: str | None) -> list[str]:
    if not coderabbit_yaml_exists(run, branch, cwd=repo_root):
        raise RuntimeError(
            f".coderabbit.yaml not found on '{branch}' (must be tracked in git); "
            "this repo's review scope (path_filters/instructions) must be defined "
            "there before running a full-repo or path audit."
        )
    files = repo_files(run, branch, scope_path, cwd=repo_root)
    if not files:
        raise RuntimeError(f"no files in scope under '{scope_path or '.'}' after applying .coderabbit.yaml path_filters")
    return files


def _audit_content_scope(
    run: Runner, repo_root: Path, branch: str, limit: int, scope_path: str | None
) -> int:
    files = _content_scope_files(run, repo_root, branch, scope_path)
    print(f"=== Auditing {scope_path or 'full repo'} ({len(files)} file(s)) ===")
    slug = _slug(scope_path or "full-repo")
    return _run_scoped(run, ScopedAudit(repo_root, slug, "orphan", None, branch, files, limit))


def _snapshot_with_untracked(run: Runner, repo_root: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(run, "read-tree", "HEAD", cwd=repo_root, env=env)
        _git(run, "add", "-A", cwd=repo_root, env=env)
        tree = _git(run, "write-tree", cwd=repo_root, env=env).stdout.strip()
    return _git(run, "commit-tree", tree, "-p", "HEAD", "-m", "audit snapshot", cwd=repo_root).stdout.strip()


def _audit_uncommitted(run: Runner, repo_root: Path, limit: int) -> int:
    files = uncommitted_files(run, cwd=repo_root)
    if not files:
        raise RuntimeError("no uncommitted changes to audit")
    if len(files) <= limit:
        print(f"=== Auditing uncommitted changes ({len(files)} file(s)) ===")
        return _run_simple(run, ["coderabbit", "review", "--uncommitted", "--agent"], cwd=repo_root)
    print(f"=== Auditing uncommitted changes ({len(files)} file(s), batching over the {limit}-file limit) ===")
    snapshot = _snapshot_with_untracked(run, repo_root)
    if not snapshot:
        raise RuntimeError("git commit-tree produced no snapshot to diff")
    return _run_scoped(run, ScopedAudit(repo_root, "uncommitted", "ref", "HEAD", snapshot, files, limit))


def _audit_branch(run: Runner, repo_root: Path, current: str, target_branch: str, limit: int) -> int:
    files = branch_diff_files(run, target_branch, cwd=repo_root)
    if not files:
        raise RuntimeError(f"no diff between '{target_branch}' and '{current}'")
    if len(files) <= limit:
        print(f"=== Auditing diff against '{target_branch}' ({len(files)} file(s)) ===")
        return _run_simple(run, ["coderabbit", "review", "--base", target_branch, "--agent"], cwd=repo_root)
    print(
        f"=== Auditing diff against '{target_branch}' ({len(files)} file(s), "
        f"batching over the {limit}-file limit) ==="
    )
    audit = ScopedAudit(repo_root, _slug(target_branch), "ref", target_branch, current, files, limit)
    return _run_scoped(run, audit)


def _audit_pr(run: Runner, repo_root: Path, pr: str, limit: int) -> int:
    print(f"=== Checking for an existing CodeRabbit review of PR {pr} ===")
    existing = run(["coderabbit", "pullrequest", pr, "--agent"], cwd=repo_root, capture_output=True, text=True)
    if existing.returncode == 0 and existing.stdout.strip():
        _write_export(existing.stdout)
        return 0
    print(f"No existing review found for PR {pr}; falling back to a live diff review.")
    original = _restore_point(run, repo_root)
    checkout = run(["gh", "pr", "checkout", pr], cwd=repo_root, capture_output=True, text=True)
    if checkout.returncode != 0:
        raise RuntimeError(f"gh pr checkout {pr} failed: {checkout.stderr.strip()}")
    try:
        return _audit_checked_out_pr(run, repo_root, pr, limit)
    finally:
        _git(run, "checkout", original, cwd=repo_root, check=False)


def _restore_point(run: Runner, repo_root: Path) -> str:
    branch = current_branch(run, cwd=repo_root)
    return _git(run, "rev-parse", "HEAD", cwd=repo_root).stdout.strip() if branch == "HEAD" else branch


def _audit_checked_out_pr(run: Runner, repo_root: Path, pr: str, limit: int) -> int:
    head_branch = current_branch(run, cwd=repo_root)
    base_branch = _pr_base_ref(run, pr, cwd=repo_root)
    files = pr_diff_files(run, pr, cwd=repo_root)
    if not files:
        raise RuntimeError(f"PR {pr} has no diffed files")
    if len(files) <= limit:
        print(f"=== Auditing PR {pr} ({len(files)} file(s)) ===")
        return _run_simple(run, ["coderabbit", "review", "--base", base_branch, "--agent"], cwd=repo_root)
    print(f"=== Auditing PR {pr} ({len(files)} file(s), batching over the {limit}-file limit) ===")
    return _run_scoped(run, ScopedAudit(repo_root, f"pr-{pr}", "ref", base_branch, head_branch, files, limit))


def _dispatch(run: Runner, args: argparse.Namespace, repo_root: Path, branch: str, limit: int) -> int:
    if args.uncommitted:
        return _audit_uncommitted(run, repo_root, limit)
    if args.pr is not None:
        return _audit_pr(run, repo_root, args.pr, limit)
    if args.branch is not None:
        return _audit_branch(run, repo_root, branch, args.branch, limit)
    return _audit_content_scope(run, repo_root, branch, limit, args.path)


def main(argv: list[str] | None = None, run: Runner = subprocess.run) -> int:
    args = build_arg_parser().parse_args(argv)
    limit = clamp_limit(args.limit)
    try:
        repo_root = Path(_git(run, "rev-parse", "--show-toplevel").stdout.strip())
        branch = current_branch(run, cwd=repo_root)
        exit_code = _dispatch(run, args, repo_root, branch, limit)
    except RuntimeError as exc:
        print(f"coderabbitFullAudit: {exc}", file=sys.stderr)
        return 1
    if exit_code == 0:
        print(f"Done. Exported to: {EXPORT_FILE}")
    return exit_code
