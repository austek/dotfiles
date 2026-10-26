import urllib.request

import pytest
from dotfiles_setup import tooling


def redirect(newurl):
    request = urllib.request.Request("https://example.com/a")
    return tooling._HttpsOnlyRedirect().redirect_request(request, None, 302, "Found", {}, newurl)


def test_redirect_to_http_is_refused():
    with pytest.raises(ValueError, match="non-https"):
        redirect("http://example.com/script.sh")


def test_redirect_to_https_is_followed():
    assert redirect("https://example.org/script.sh").full_url == "https://example.org/script.sh"


def test_plain_http_urls_are_refused_up_front():
    with pytest.raises(ValueError, match="non-https"):
        tooling._require_https("http://example.com")


def test_a_missing_executable_is_exit_status_127_not_an_exception():
    result = tooling.run_command(["definitely-not-a-real-command-xyz"], capture_output=True)
    assert result.returncode == tooling.COMMAND_NOT_FOUND
    assert "definitely-not-a-real-command-xyz" in result.stderr


def test_an_existing_executable_runs_normally():
    result = tooling.run_command(["true"])
    assert result.returncode == 0


def test_a_failing_executable_keeps_its_own_status():
    assert tooling.run_command(["false"]).returncode == 1
