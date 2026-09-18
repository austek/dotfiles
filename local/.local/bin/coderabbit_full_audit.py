"""CodeRabbit audit runner behind the `coderabbitFullAudit` command.

Mirrors the five review scopes the `/coderabbit-audit` Claude command resolves
(uncommitted changes, a path, a PR, a branch, or the full repo) and keeps every
`coderabbit review` call under CodeRabbit's free-tier file-count ceiling by
splitting an over-limit scope into multiple review calls, each built from a
scratch git worktree so the extra calls never touch the caller's working tree.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FREE_TIER_CEILING = 150
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
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--uncommitted", action="store_true", help="review uncommitted working-tree changes"
    )
    scope.add_argument(
        "--path", metavar="PATH", help="full-content audit of PATH (not just its diff)"
    )
    scope.add_argument("--pr", metavar="NUM|URL", help="review a pull request")
    scope.add_argument("--branch", metavar="NAME", help="review the diff against NAME")
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
    return parser


def clamp_limit(limit: int) -> int:
    if limit > FREE_TIER_CEILING:
        print(
            f"coderabbitFullAudit: --limit {limit} exceeds the free-tier ceiling of "
            f"{FREE_TIER_CEILING}; clamping to {FREE_TIER_CEILING}.",
            file=sys.stderr,
        )
        return FREE_TIER_CEILING
    return limit


def chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "scope"


def _git(run, *args, cwd=None, check=True):
    result = run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def current_branch(run, cwd=None) -> str:
    return _git(run, "rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).stdout.strip()


def coderabbit_yaml_exists(run, branch: str, cwd=None) -> bool:
    result = run(
        ["git", "cat-file", "-e", f"{branch}:.coderabbit.yaml"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def negated_path_filters(run, branch: str, cwd=None) -> list[str]:
    result = run(["git", "show", f"{branch}:.coderabbit.yaml"], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return _parse_negated_filters(result.stdout)


def _parse_negated_filters(yaml_text: str) -> list[str]:
    patterns = []
    in_filters = False
    for line in yaml_text.splitlines():
        stripped = line.strip()
        if re.match(r"^path_filters\s*:", stripped):
            in_filters = True
            continue
        if not in_filters:
            continue
        if re.match(r"^[A-Za-z_]+\s*:", stripped):
            break
        match = re.search(r"""["']!([^"']+)["']""", stripped)
        if match:
            patterns.append(match.group(1))
    return patterns


def repo_files(run, branch: str, scope_path: str | None = None, cwd=None) -> list[str]:
    pathspec = [scope_path] if scope_path else ["."]
    result = _git(run, "ls-tree", "-r", "--name-only", branch, "--", *pathspec, cwd=cwd)
    files = [f for f in result.stdout.splitlines() if f]
    if scope_path and ".coderabbit.yaml" not in files and coderabbit_yaml_exists(run, branch, cwd=cwd):
        files.append(".coderabbit.yaml")
    excluded: set[str] = set()
    for pattern in negated_path_filters(run, branch, cwd=cwd):
        matched = _git(
            run, "ls-tree", "-r", "--name-only", branch, "--", f":(glob){pattern}", cwd=cwd, check=False
        )
        excluded.update(f for f in matched.stdout.splitlines() if f)
    return [f for f in files if f not in excluded]


def uncommitted_files(run, cwd=None) -> list[str]:
    result = _git(run, "status", "--porcelain", cwd=cwd)
    files = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:].strip('"')
        if " -> " in path:
            path = path.split(" -> ")[-1]
        files.append(path)
    return files


def branch_diff_files(run, target_branch: str, cwd=None) -> list[str]:
    result = _git(run, "diff", "--name-only", f"{target_branch}...HEAD", cwd=cwd)
    return [f for f in result.stdout.splitlines() if f]


def pr_diff_files(run, pr: str, cwd=None) -> list[str]:
    result = run(["gh", "pr", "diff", pr, "--name-only"], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh pr diff {pr} --name-only failed: {result.stderr.strip()}")
    return [f for f in result.stdout.splitlines() if f]


def _pr_base_ref(run, pr: str, cwd=None) -> str:
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


def _run_simple(run, cmd: list[str], cwd=None) -> int:
    result = run(cmd, cwd=cwd, capture_output=True, text=True)
    _write_export(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def _setup_baseline(run, worktree_dir: Path, base_branch: str, baseline_mode: str, base_ref: str | None) -> None:
    if baseline_mode == "orphan":
        _git(run, "checkout", "--orphan", base_branch, cwd=worktree_dir)
        _git(run, "rm", "-rf", ".", cwd=worktree_dir, check=False)
        _git(run, "commit", "--allow-empty", "-m", "empty initial commit", cwd=worktree_dir)
    else:
        _git(run, "checkout", "-b", base_branch, base_ref, cwd=worktree_dir)


def _run_one_batch(run, worktree_dir: Path, base_branch: str, target_ref: str, batch_files: list[str], batch_num: int, total: int) -> int:
    code_branch = f"{base_branch}-code-{batch_num}"
    _git(run, "checkout", "-b", code_branch, base_branch, cwd=worktree_dir)
    _git(run, "checkout", target_ref, "--", *batch_files, cwd=worktree_dir)
    _git(run, "add", ".", cwd=worktree_dir)
    _git(run, "commit", "-m", f"batch {batch_num}/{total} snapshot for audit", cwd=worktree_dir)
    result = run(
        ["coderabbit", "review", "--base", base_branch, "--agent"],
        cwd=worktree_dir,
        capture_output=True,
        text=True,
    )
    if total > 1:
        _append_export(f"\n## Batch {batch_num}/{total} ({len(batch_files)} file(s))\n\n" + result.stdout)
    else:
        _append_export(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
    _git(run, "checkout", base_branch, cwd=worktree_dir, check=False)
    _git(run, "branch", "-D", code_branch, cwd=worktree_dir, check=False)
    return result.returncode


def _run_scoped(run, repo_root: Path, slug: str, baseline_mode: str, base_ref: str | None, target_ref: str, files: list[str], limit: int) -> int:
    batches = chunk(files, limit)
    worktree_dir = repo_root.parent / f"cr-audit-scratch-{slug}"
    base_branch = f"audit-base-{slug}"
    _git(run, "worktree", "add", "--detach", str(worktree_dir), cwd=repo_root)
    try:
        _setup_baseline(run, worktree_dir, base_branch, baseline_mode, base_ref)
        EXPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_FILE.write_text("")
        exit_code = 0
        for i, batch in enumerate(batches, start=1):
            print(f"--- batch {i}/{len(batches)} ({len(batch)} file(s)) ---")
            batch_code = _run_one_batch(run, worktree_dir, base_branch, target_ref, batch, i, len(batches))
            exit_code = exit_code or batch_code
        return exit_code
    finally:
        _git(run, "worktree", "remove", "--force", str(worktree_dir), cwd=repo_root, check=False)
        _git(run, "branch", "-D", base_branch, cwd=repo_root, check=False)
        _git(run, "worktree", "prune", cwd=repo_root, check=False)


def _audit_content_scope(run, repo_root: Path, branch: str, limit: int, scope_path: str | None) -> int:
    if not coderabbit_yaml_exists(run, branch, cwd=repo_root):
        raise RuntimeError(
            f".coderabbit.yaml not found on '{branch}' (must be tracked in git); "
            "this repo's review scope (path_filters/instructions) must be defined "
            "there before running a full-repo or path audit."
        )
    files = repo_files(run, branch, scope_path, cwd=repo_root)
    if not files:
        raise RuntimeError(f"no files in scope under '{scope_path or '.'}' after applying .coderabbit.yaml path_filters")
    label = scope_path or "full repo"
    print(f"=== Auditing {label} ({len(files)} file(s)) ===")
    slug = _slug(scope_path or "full-repo")
    return _run_scoped(run, repo_root, slug, "orphan", None, branch, files, limit)


def _audit_uncommitted(run, repo_root: Path, limit: int) -> int:
    files = uncommitted_files(run, cwd=repo_root)
    if not files:
        raise RuntimeError("no uncommitted changes to audit")
    if len(files) <= limit:
        print(f"=== Auditing uncommitted changes ({len(files)} file(s)) ===")
        return _run_simple(run, ["coderabbit", "review", "--uncommitted", "--agent"], cwd=repo_root)
    print(f"=== Auditing uncommitted changes ({len(files)} file(s), batching over the {limit}-file limit) ===")
    snapshot = _git(run, "stash", "create", cwd=repo_root).stdout.strip()
    if not snapshot:
        raise RuntimeError("git stash create produced no snapshot to diff")
    return _run_scoped(run, repo_root, "uncommitted", "ref", "HEAD", snapshot, files, limit)


def _audit_branch(run, repo_root: Path, current: str, target_branch: str, limit: int) -> int:
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
    return _run_scoped(run, repo_root, _slug(target_branch), "ref", target_branch, current, files, limit)


def _audit_pr(run, repo_root: Path, pr: str, limit: int) -> int:
    print(f"=== Checking for an existing CodeRabbit review of PR {pr} ===")
    existing = run(["coderabbit", "pullrequest", pr, "--agent"], cwd=repo_root, capture_output=True, text=True)
    if existing.returncode == 0 and existing.stdout.strip():
        _write_export(existing.stdout)
        return 0

    print(f"No existing review found for PR {pr}; falling back to a live diff review.")
    original_branch = current_branch(run, cwd=repo_root)
    checkout = run(["gh", "pr", "checkout", pr], cwd=repo_root, capture_output=True, text=True)
    if checkout.returncode != 0:
        raise RuntimeError(f"gh pr checkout {pr} failed: {checkout.stderr.strip()}")
    try:
        head_branch = current_branch(run, cwd=repo_root)
        base_branch = _pr_base_ref(run, pr, cwd=repo_root)
        files = pr_diff_files(run, pr, cwd=repo_root)
        if not files:
            raise RuntimeError(f"PR {pr} has no diffed files")
        if len(files) <= limit:
            print(f"=== Auditing PR {pr} ({len(files)} file(s)) ===")
            return _run_simple(run, ["coderabbit", "review", "--base", base_branch, "--agent"], cwd=repo_root)
        print(f"=== Auditing PR {pr} ({len(files)} file(s), batching over the {limit}-file limit) ===")
        return _run_scoped(run, repo_root, f"pr-{pr}", "ref", base_branch, head_branch, files, limit)
    finally:
        _git(run, "checkout", original_branch, cwd=repo_root, check=False)


def main(argv: list[str] | None = None, run=subprocess.run) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    limit = clamp_limit(args.limit)
    try:
        repo_root = Path(_git(run, "rev-parse", "--show-toplevel").stdout.strip())
        branch = current_branch(run, cwd=repo_root)
        if args.path is not None:
            exit_code = _audit_content_scope(run, repo_root, branch, limit, args.path)
        elif args.uncommitted:
            exit_code = _audit_uncommitted(run, repo_root, limit)
        elif args.pr is not None:
            exit_code = _audit_pr(run, repo_root, args.pr, limit)
        elif args.branch is not None:
            exit_code = _audit_branch(run, repo_root, branch, args.branch, limit)
        else:
            exit_code = _audit_content_scope(run, repo_root, branch, limit, None)
    except RuntimeError as exc:
        print(f"coderabbitFullAudit: {exc}", file=sys.stderr)
        return 1
    if exit_code == 0:
        print(f"Done. Exported to: {EXPORT_FILE}")
    return exit_code
