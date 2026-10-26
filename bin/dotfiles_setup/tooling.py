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


def fetch_https(url: str) -> str:
    _require_https(url)
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode()


def download_https(url: str, dest: Path) -> None:
    _require_https(url)
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response, dest.open("wb") as handle:
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
    download: Callable[[str, Path], None] = download_https
    redirect: Callable[[str], str | None] = redirect_location


def dry_run_all(t: Tooling, *messages: str) -> bool:
    shown = [t.logger.dry_run_notice(message) for message in messages]
    return all(shown)
