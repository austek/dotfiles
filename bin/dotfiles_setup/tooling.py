"""Shared plumbing for the installers in tools.py and release_installers.py:
the injected collaborators (run, fetch, download, redirect) and their https-only defaults."""
from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
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
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirect)


def fetch_bytes_https(url: str) -> bytes:
    _require_https(url)
    with _OPENER.open(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_https(url: str) -> str:
    return fetch_bytes_https(url).decode()


def download_https(url: str, dest: Path) -> None:
    _require_https(url)
    with _OPENER.open(url, timeout=FETCH_TIMEOUT_SECONDS) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def redirect_location(url: str) -> str | None:
    _require_https(url)
    request = urllib.request.Request(url, method="HEAD")
    try:
        urllib.request.build_opener(_NoRedirect).open(request, timeout=FETCH_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        return error.headers.get("Location")
    return None


@dataclass(frozen=True)
class Tooling:
    logger: Logger
    home: Path
    run: Callable[..., Any] = subprocess.run
    fetch: Callable[[str], str] = fetch_https
    fetch_bytes: Callable[[str], bytes] = fetch_bytes_https
    download: Callable[[str, Path], None] = download_https
    redirect: Callable[[str], str | None] = redirect_location


# Returning False aborts the run; None or True continues.
Installer = Callable[[Tooling], bool | None]


def dry_run_all(t: Tooling, *messages: str) -> bool:
    shown = list(map(t.logger.dry_run_notice, messages))
    return all(shown)
