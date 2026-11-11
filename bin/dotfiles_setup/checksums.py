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


class DigestTable(dict[str, str]):
    """Maps each URL to its expected digest. `unavailable` gives the reason the listing could not be read, or stays `None` when `load` read it."""

    unavailable: str | None = None


def _unavailable(path: Path, error: OSError | UnicodeDecodeError) -> str:
    if isinstance(error, FileNotFoundError):
        return f"{path} not found"
    reason = getattr(error, "strerror", None) or type(error).__name__
    return f"cannot read {path}: {reason}"


def load(path: Path) -> DigestTable:
    table = DigestTable()
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError) as error:
        table.unavailable = _unavailable(path, error)
        return table
    for line in lines:
        digest, _, url = line.partition("#")[0].strip().partition(" ")
        if _DIGEST.fullmatch(digest) and url.strip():
            table[url.strip()] = digest
    return table


def _missing_digest(table: Mapping[str, str], url: str) -> str:
    reason = table.unavailable if isinstance(table, DigestTable) else None
    if reason is not None:
        return f"cannot verify {url}: {reason}"
    return f"no digest recorded for {url}; add one to packages/{FILE_NAME}"


def verify(table: Mapping[str, str] | None, url: str, data: bytes) -> None:
    """Raises ChecksumError unless `data` matches the digest recorded for `url`; `None` disables the check."""
    if table is None:
        return
    expected = table.get(url)
    if expected is None:
        raise ChecksumError(_missing_digest(table, url))
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise DigestMismatchError(f"digest mismatch for {url}: expected {expected}, got {actual}")


def verify_file(table: Mapping[str, str] | None, url: str, path: Path) -> None:
    if table is not None:
        verify(table, url, path.read_bytes())
