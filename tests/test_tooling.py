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


def test_the_token_is_dropped_when_a_redirect_leaves_the_host(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    request = tooling._request("https://api.github.com/repos/x/y")
    handler = tooling._HttpsOnlyRedirect()
    elsewhere = handler.redirect_request(request, None, 302, "Found", {}, "https://objects.example.com/blob")
    same_host = handler.redirect_request(request, None, 302, "Found", {}, "https://api.github.com/repos/x/z")
    assert elsewhere.get_header("Authorization") is None
    assert same_host.get_header("Authorization") == "Bearer t0ken"


def test_plain_http_urls_are_refused_up_front():
    with pytest.raises(ValueError, match="non-https"):
        tooling._require_https("http://example.com")


def test_requests_identify_themselves_instead_of_using_the_urllib_agent():
    request = tooling._request("https://astral.sh/uv/install.sh")
    assert request.get_header("User-agent") == tooling.USER_AGENT


def test_the_github_token_goes_only_to_the_github_api(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert tooling._request("https://api.github.com/repos/x/y").get_header("Authorization") == "Bearer t0ken"
    assert tooling._request("https://example.com/x").get_header("Authorization") is None
    assert tooling._request("https://github.com/x/y/releases/download/v1/a.deb").get_header("Authorization") is None


def test_no_token_means_no_authorization_header(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert tooling._request("https://api.github.com/repos/x/y").get_header("Authorization") is None


def test_a_non_https_request_is_refused():
    with pytest.raises(ValueError, match="non-https"):
        tooling._request("http://example.com")


def test_a_missing_executable_is_exit_status_127_not_an_exception():
    result = tooling.run_command(["definitely-not-a-real-command-xyz"], capture_output=True)
    assert result.returncode == tooling.COMMAND_NOT_FOUND
    assert "definitely-not-a-real-command-xyz" in result.stderr


def test_an_existing_executable_runs_normally():
    result = tooling.run_command(["true"])
    assert result.returncode == 0


def test_a_failing_executable_keeps_its_own_status():
    assert tooling.run_command(["false"]).returncode == 1
