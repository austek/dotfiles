"""Apply a baseline branch-protection ruleset to an owner's public repos.

Org-wide rulesets need GitHub Team; this is the free-plan equivalent. A PUT replaces the whole ruleset, so the
current ruleset is fetched and only the managed rules are merged into it: other rules, bypass actors, conditions
and an existing pull_request rule's parameters survive. An unset REQUIRE_PR keeps the repo's pull_request rule.

    github-rulesets [owner]               # default owner: ZirekHQ
    github-rulesets --dry-run austek      # print the calls and payloads; GETs only (or DRY_RUN=1)
    REPOS="a b" github-rulesets austek    # explicit list, skips discovery
    INCLUDE_FORKS=1 ...                   # forks are skipped by default
    REQUIRE_PR=1 ...                      # also require a PR (0 approvals); REQUIRE_PR=0 drops the requirement
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

DEFAULT_OWNER = "ZirekHQ"
RULESET_NAME = "baseline"
MANAGED_RULES = ("deletion", "non_fast_forward", "required_linear_history")
LIST_JQ = r'.[] | select(.isArchived == false) | "\(.visibility) \(.isFork) \(.name)"'
ID_JQ = f'[.[] | select(.name == "{RULESET_NAME}")] | first | .id // empty'
PULL_REQUEST_RULE = {
    "type": "pull_request",
    "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": True,
        # Omitting this defaults to allowing "merge", which required_linear_history rejects.
        "allowed_merge_methods": ["squash", "rebase"],
    },
}
Gh = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Settings:
    owner: str
    dry_run: bool
    require_pr: str
    include_forks: bool
    repos: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    visibility: str
    is_fork: bool
    name: str


@dataclass(frozen=True)
class Outcome:
    status: str
    lines: tuple[str, ...] = ()


def parse_settings(argv: Sequence[str], environ: Mapping[str, str]) -> Settings:
    flags = [a for a in argv if a == "--dry-run"]
    positional = [a for a in argv if a != "--dry-run"]
    return Settings(
        owner=positional[0] if positional else DEFAULT_OWNER,
        dry_run=bool(flags) or environ.get("DRY_RUN", "0") == "1",
        require_pr=environ.get("REQUIRE_PR", "preserve"),
        include_forks=environ.get("INCLUDE_FORKS", "0") == "1",
        repos=tuple(environ.get("REPOS", "").split()),
    )


def run_gh(args: Sequence[str], stdin: str | None = None, merge_stderr: bool = False) -> subprocess.CompletedProcess[str]:
    stderr = subprocess.STDOUT if merge_stderr else subprocess.PIPE
    return subprocess.run(["gh", *args], input=stdin, stdout=subprocess.PIPE, stderr=stderr, text=True, check=False)


def build_payload(want_pr: bool, current: Mapping[str, object]) -> dict[str, object]:
    """The ruleset to PUT: the managed rules plus everything the current ruleset already had."""
    rules = current.get("rules", [])
    kept = [r for r in rules if r["type"] not in (*MANAGED_RULES, "pull_request")]
    old_pr = [r for r in rules if r["type"] == "pull_request"]
    pull_request = [old_pr[0] if old_pr else PULL_REQUEST_RULE] if want_pr else []
    payload: dict[str, object] = {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [*({"type": t} for t in MANAGED_RULES), *kept, *pull_request],
    }
    payload.update({k: current[k] for k in ("target", "conditions", "bypass_actors") if k in current})
    return payload


def discover(settings: Settings, gh: Gh) -> list[Candidate]:
    if settings.repos:
        return [Candidate("PUBLIC", False, name) for name in settings.repos]
    listing = gh(["repo", "list", settings.owner, "--limit", "200", "--json", "name,isArchived,isFork,visibility", "--jq", LIST_JQ])
    return [_candidate(line) for line in (listing.stdout or "").splitlines() if len(line.split()) == 3]


def _candidate(line: str) -> Candidate:
    visibility, is_fork, name = line.split()
    return Candidate(visibility, is_fork == "true", name)


def ruleset_id(settings: Settings, gh: Gh, repo: str) -> str | None:
    """The baseline ruleset's id ("" when none exists), or None when rulesets are unavailable."""
    result = gh(["api", f"repos/{settings.owner}/{repo}/rulesets", "--jq", ID_JQ])
    return (result.stdout or "").strip() if result.returncode == 0 else None


def read_ruleset(settings: Settings, gh: Gh, repo: str, existing: str) -> dict[str, object] | None:
    result = gh(["api", f"repos/{settings.owner}/{repo}/rulesets/{existing}"])
    try:
        current = json.loads(result.stdout) if result.returncode == 0 else None
    except json.JSONDecodeError:
        return None
    return current if isinstance(current, dict) else None


def wants_pull_request(require_pr: str, current: Mapping[str, object]) -> bool:
    if require_pr in ("0", "1"):
        return require_pr == "1"
    return any(r["type"] == "pull_request" for r in current.get("rules", []))


def process_repo(settings: Settings, gh: Gh, candidate: Candidate) -> Outcome:
    if candidate.visibility != "PUBLIC":
        return Outcome("private")
    if candidate.is_fork and not settings.include_forks:
        return Outcome("fork")
    label = f"{settings.owner}/{candidate.name}"
    existing = ruleset_id(settings, gh, candidate.name)
    if existing is None:
        return Outcome("failed", (f"{label}: FAIL (rulesets unavailable)",))
    current = read_ruleset(settings, gh, candidate.name, existing) if existing else {}
    if current is None:
        return Outcome("failed", (f"{label}: FAIL (cannot read ruleset {existing})",))
    return apply(settings, gh, candidate.name, existing, current)


def apply(settings: Settings, gh: Gh, repo: str, existing: str, current: dict[str, object]) -> Outcome:
    label = f"{settings.owner}/{repo}"
    want_pr = wants_pull_request(settings.require_pr, current)
    method, endpoint, verb = (
        ("PUT", f"repos/{settings.owner}/{repo}/rulesets/{existing}", "updated")
        if existing else ("POST", f"repos/{settings.owner}/{repo}/rulesets", "created")
    )
    payload = json.dumps(build_payload(want_pr, current))
    if settings.dry_run:
        return Outcome("ok", (f"{label}: would run: gh api -X {method} {endpoint} --input - (pr={int(want_pr)})", payload))
    jq = f'"{verb} (pr={int(want_pr)})"'
    result = gh(["api", "-X", method, endpoint, "--input", "-", "--jq", jq], stdin=payload, merge_stderr=True)
    output = (result.stdout or "").rstrip("\n")
    if result.returncode == 0:
        return Outcome("ok", (f"{label}: {output}",))
    return Outcome("failed", (f"{label}: FAIL ({output.splitlines()[0] if output else ''})",))


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None, gh: Gh = run_gh) -> int:
    settings = parse_settings(sys.argv[1:] if argv is None else argv, os.environ if environ is None else environ)
    if gh is run_gh and shutil.which("gh") is None:
        print("gh not found", file=sys.stderr)
        return 1
    outcomes = [process_repo(settings, gh, c) for c in discover(settings, gh)]
    return report(outcomes)


def report(outcomes: Sequence[Outcome]) -> int:
    for outcome in outcomes:
        for line in outcome.lines:
            print(line)
    failed = sum(o.status == "failed" for o in outcomes)
    private = sum(o.status == "private" for o in outcomes)
    forks = sum(o.status == "fork" for o in outcomes)
    print()
    print(f"skipped: {private} private (rulesets need GitHub Pro), {forks} forks")
    print("Status checks are not set here: required check names differ per repo.")
    if failed:
        print(f"{failed} repositories failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
