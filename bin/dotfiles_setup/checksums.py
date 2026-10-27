"""Pinned SHA-256 digests for downloaded packages and installer scripts, read from packages/checksums.txt.

Each non-comment line is `<sha256>  <url>`. A download whose URL has no line, or whose content differs, is refused."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

FILE_NAME = "checksums.txt"
_DIGEST = re.compile(r"[0-9a-f]{64}")


class ChecksumError(ValueError):
    pass


class DigestMismatchError(ChecksumError):
    pass


def load(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return table
    for line in lines:
        digest, _, url = line.partition("#")[0].strip().partition(" ")
        if _DIGEST.fullmatch(digest) and url.strip():
            table[url.strip()] = digest
    return table


def verify(table: Mapping[str, str] | None, url: str, data: bytes) -> None:
    """Raises ChecksumError unless `data` matches the digest recorded for `url`; `None` disables the check."""
    if table is None:
        return
    expected = table.get(url)
    if expected is None:
        raise ChecksumError(f"no digest recorded for {url}; add one to packages/{FILE_NAME}")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise DigestMismatchError(f"digest mismatch for {url}: expected {expected}, got {actual}")


def verify_file(table: Mapping[str, str] | None, url: str, path: Path) -> None:
    if table is not None:
        verify(table, url, path.read_bytes())
