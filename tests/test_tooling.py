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
