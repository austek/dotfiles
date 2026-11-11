import json
import subprocess
from pathlib import Path

import github_rulesets as grs
from test_local_scripts import _path_without, _stub

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "github-rulesets"


def _run_rulesets(tmp_path, gh_body, without=()):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    if gh_body is not None:
        _stub(stubs, "gh", gh_body)
    env = {"PATH": _path_without(tmp_path, stubs, *without), "REPOS": "alpha"}
    return subprocess.run([str(SCRIPT), "owner"], env=env, capture_output=True, text=True, check=False, timeout=60)


MANAGED = ["deletion", "non_fast_forward", "required_linear_history"]
EXISTING_PR_RULE = {
    "type": "pull_request",
    "parameters": {"required_approving_review_count": 2, "allowed_merge_methods": ["squash"]},
}
EXISTING = {
    "id": 42,
    "name": "baseline",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["refs/heads/release"], "exclude": []}},
    "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
    "rules": [{"type": "deletion"}, {"type": "required_signatures"}, EXISTING_PR_RULE],
}


def _gh_reading(tmp_path, existing=None, repo_list=""):
    """A gh stub that answers repo list, the ruleset id lookup and the ruleset read."""
    payload = tmp_path / "existing.json"
    payload.write_text(json.dumps(existing or {}))
    answer = "echo 42" if existing else ":"
    return (
        'case "$*" in\n'
        f"  *'repo list'*) printf '%s' '{repo_list}' ;;\n"
        f'  *rulesets/42*) cat "{payload}" ;;\n'
        f"  *rulesets*) {answer} ;;\n"
        "esac\n"
    )


def _dry_run(tmp_path, gh_body, **env):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub(stubs, "gh", gh_body)
    full_env = {"PATH": _path_without(tmp_path, stubs), "REPOS": "alpha", **env}
    return subprocess.run(
        [str(SCRIPT), "--dry-run", "owner"], env=full_env, capture_output=True, text=True, check=False, timeout=60,
    )


def _payload(result):
    line = next(line for line in result.stdout.splitlines() if line.startswith("{"))
    return json.loads(line)


def _types(payload):
    return [rule["type"] for rule in payload["rules"]]


def test_a_repo_without_a_ruleset_gets_a_new_baseline(tmp_path):
    result = _dry_run(tmp_path, _gh_reading(tmp_path))
    assert result.returncode == 0
    assert "owner/alpha: would run: gh api -X POST repos/owner/alpha/rulesets --input - (pr=0)" in result.stdout
    payload = _payload(result)
    assert _types(payload) == MANAGED
    assert payload["name"] == "baseline"
    assert payload["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]


def test_an_existing_ruleset_keeps_its_other_rules_bypass_actors_and_conditions(tmp_path):
    result = _dry_run(tmp_path, _gh_reading(tmp_path, EXISTING))
    assert "would run: gh api -X PUT repos/owner/alpha/rulesets/42 --input - (pr=1)" in result.stdout
    payload = _payload(result)
    assert _types(payload) == [*MANAGED, "required_signatures", "pull_request"]
    assert payload["bypass_actors"] == EXISTING["bypass_actors"]
    assert payload["conditions"] == EXISTING["conditions"]


def test_an_unset_require_pr_keeps_the_existing_pull_request_rule_untouched(tmp_path):
    payload = _payload(_dry_run(tmp_path, _gh_reading(tmp_path, EXISTING)))
    assert payload["rules"][-1] == EXISTING_PR_RULE


def test_require_pr_zero_drops_the_pull_request_rule(tmp_path):
    result = _dry_run(tmp_path, _gh_reading(tmp_path, EXISTING), REQUIRE_PR="0")
    assert "(pr=0)" in result.stdout
    assert "pull_request" not in _types(_payload(result))


def test_require_pr_one_adds_a_pull_request_rule_that_allows_no_merge_commits(tmp_path):
    result = _dry_run(tmp_path, _gh_reading(tmp_path), REQUIRE_PR="1")
    rule = _payload(result)["rules"][-1]
    assert rule["type"] == "pull_request"
    assert rule["parameters"]["required_approving_review_count"] == 0
    assert rule["parameters"]["allowed_merge_methods"] == ["squash", "rebase"]


def test_require_pr_one_keeps_an_existing_pull_request_rule_as_it_is(tmp_path):
    result = _dry_run(tmp_path, _gh_reading(tmp_path, EXISTING), REQUIRE_PR="1")
    assert _payload(result)["rules"][-1] == EXISTING_PR_RULE


def test_private_repos_and_forks_are_skipped_unless_forks_are_included(tmp_path):
    listing = "PUBLIC false alpha\nPRIVATE false hidden\nPUBLIC true forked\n"
    result = _dry_run(tmp_path, _gh_reading(tmp_path, repo_list=listing), REPOS="")
    assert "owner/alpha: would run" in result.stdout
    assert "owner/forked" not in result.stdout
    assert "owner/hidden" not in result.stdout
    assert "skipped: 1 private (rulesets need GitHub Pro), 1 forks" in result.stdout


def test_forks_are_included_on_request(tmp_path):
    listing = "PUBLIC false alpha\nPUBLIC true forked\n"
    result = _dry_run(tmp_path, _gh_reading(tmp_path, repo_list=listing), REPOS="", INCLUDE_FORKS="1")
    assert "owner/forked: would run" in result.stdout
    assert "0 forks" in result.stdout


def test_a_write_reports_what_gh_printed(tmp_path):
    gh = 'case "$*" in\n  *-X\\ POST*) cat >/dev/null; echo "created (pr=0)" ;;\n  *rulesets*) : ;;\nesac\n'
    result = subprocess.run(
        [str(SCRIPT), "owner"], env={"PATH": _path_without(tmp_path, _stub_dir(tmp_path, gh)), "REPOS": "alpha"},
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0
    assert "owner/alpha: created (pr=0)" in result.stdout


def _stub_dir(tmp_path, gh_body):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub(stubs, "gh", gh_body)
    return stubs


def test_an_existing_ruleset_that_is_not_json_is_a_read_failure(tmp_path):
    gh = 'case "$*" in\n  *rulesets/42*) echo "not json" ;;\n  *rulesets*) echo 42 ;;\nesac\n'
    result = _dry_run(tmp_path, gh)
    assert result.returncode == 1
    assert "owner/alpha: FAIL (cannot read ruleset 42)" in result.stdout


def test_settings_default_to_the_zirek_owner_and_preserve_the_pull_request_rule():
    settings = grs.parse_settings([], {})
    assert (settings.owner, settings.dry_run, settings.require_pr, settings.include_forks, settings.repos) == (
        "ZirekHQ", False, "preserve", False, (),
    )


def test_settings_read_the_flag_the_environment_and_the_explicit_repo_list():
    settings = grs.parse_settings(["--dry-run", "austek"], {"REPOS": "a b", "INCLUDE_FORKS": "1", "REQUIRE_PR": "1"})
    assert (settings.owner, settings.dry_run, settings.require_pr, settings.include_forks, settings.repos) == (
        "austek", True, "1", True, ("a", "b"),
    )
    assert grs.parse_settings([], {"DRY_RUN": "1"}).dry_run


def test_build_payload_for_nothing_has_only_the_managed_rules():
    payload = grs.build_payload(False, {})
    assert [r["type"] for r in payload["rules"]] == list(grs.MANAGED_RULES)
    assert "bypass_actors" not in payload


def test_build_payload_never_duplicates_a_managed_rule():
    current = {"rules": [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "required_signatures"}]}
    types = [r["type"] for r in grs.build_payload(False, current)["rules"]]
    assert types == [*grs.MANAGED_RULES, "required_signatures"]


def test_wants_pull_request_follows_the_setting_or_the_current_rules():
    has_pr = {"rules": [{"type": "pull_request"}]}
    assert grs.wants_pull_request("1", {})
    assert not grs.wants_pull_request("0", has_pr)
    assert grs.wants_pull_request("preserve", has_pr)
    assert not grs.wants_pull_request("preserve", {})


def test_a_failed_repository_listing_fails_the_run(tmp_path):
    result = _dry_run(tmp_path, 'echo "HTTP 401: bad credentials" >&2\nexit 1\n', REPOS="")
    assert result.returncode == 1
    assert "cannot list repositories of owner: HTTP 401: bad credentials" in result.stderr
    assert "skipped:" not in result.stdout


def test_it_stops_when_gh_is_not_installed(tmp_path):
    result = _run_rulesets(tmp_path, None, without=("gh",))
    assert result.returncode == 1
    assert "gh not found" in result.stderr


def test_it_fails_a_repo_whose_rulesets_are_unavailable(tmp_path):
    result = _run_rulesets(tmp_path, "exit 1\n")
    assert result.returncode == 1
    assert "owner/alpha: FAIL (rulesets unavailable)" in result.stdout
    assert "1 repositories failed" in result.stderr


def test_it_fails_a_repo_whose_existing_ruleset_cannot_be_read(tmp_path):
    result = _run_rulesets(tmp_path, 'case "$*" in\n  *rulesets/42*) exit 1 ;;\n  *rulesets*) echo 42 ;;\nesac\n')
    assert result.returncode == 1
    assert "owner/alpha: FAIL (cannot read ruleset 42)" in result.stdout
    assert "1 repositories failed" in result.stderr


def test_it_reports_the_first_line_of_a_failed_write(tmp_path):
    gh = 'if [[ "$*" == *"-X"* ]]; then\n  cat > /dev/null\n  printf "HTTP 403: forbidden\\nextra\\n"\n  exit 1\nfi\n'
    result = _run_rulesets(tmp_path, gh)
    assert result.returncode == 1
    assert "owner/alpha: FAIL (HTTP 403: forbidden)" in result.stdout
    assert "extra" not in result.stdout
