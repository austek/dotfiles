import subprocess
from pathlib import Path

from test_local_scripts import _path_without, _stub

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "github-rulesets.sh"


def _run_rulesets(tmp_path, gh_body, without=()):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    if gh_body is not None:
        _stub(stubs, "gh", gh_body)
    env = {"PATH": _path_without(tmp_path, stubs, *without), "REPOS": "alpha"}
    return subprocess.run([str(SCRIPT), "owner"], env=env, capture_output=True, text=True, check=False, timeout=60)


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
