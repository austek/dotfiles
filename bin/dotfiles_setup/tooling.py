"""Shared plumbing for the installers in tools.py and release_installers.py:
the injected collaborators (run, fetch, download, redirect) and their https-only defaults."""
from __future__ import annotations

import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotfiles_setup.log import Logger

FETCH_TIMEOUT_SECONDS = 60


def _require_https(url: str) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-https URL: {url}")


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _require_https(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirect)
USER_AGENT = "dotfiles-setup"
GITHUB_API = "https://api.github.com/"


def _request(url: str, method: str | None = None) -> urllib.request.Request:
    """Hosts such as astral.sh refuse urllib's default agent; the GitHub API rate-limits anonymous callers."""
    _require_https(url)
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(GITHUB_API):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers, method=method)


def fetch_bytes_https(url: str) -> bytes:
    with _OPENER.open(_request(url), timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_https(url: str) -> str:
    return fetch_bytes_https(url).decode()


def download_https(url: str, dest: Path) -> None:
    with _OPENER.open(_request(url), timeout=FETCH_TIMEOUT_SECONDS) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def redirect_location(url: str) -> str | None:
    request = _request(url, method="HEAD")
    try:
        urllib.request.build_opener(_NoRedirect).open(request, timeout=FETCH_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        return error.headers.get("Location")
    return None


COMMAND_NOT_FOUND = 127


def run_command(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Runs a command like a shell does: a missing executable is exit status 127, not an exception."""
    try:
        return subprocess.run(argv, check=False, **kwargs)
    except FileNotFoundError as error:
        return subprocess.CompletedProcess(argv, COMMAND_NOT_FOUND, stdout=None, stderr=str(error))


@dataclass(frozen=True)
class Tooling:
    logger: Logger
    home: Path
    run: Callable[..., Any] = run_command
    fetch: Callable[[str], str] = fetch_https
    fetch_bytes: Callable[[str], bytes] = fetch_bytes_https
    download: Callable[[str, Path], None] = download_https
    redirect: Callable[[str], str | None] = redirect_location
    checksums: Mapping[str, str] | None = None


# Returning False aborts the run; None or True continues.
Installer = Callable[[Tooling], bool | None]


def dry_run_all(t: Tooling, *messages: str) -> bool:
    shown = list(map(t.logger.dry_run_notice, messages))
    return all(shown)
