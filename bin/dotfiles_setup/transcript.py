"""A private, per-run log of everything the installer said and every command it ran with the output it captured."""
from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

KEPT_TRANSCRIPTS = 10
PREFIX = "install-"
SUFFIX = ".log"


@dataclass(frozen=True)
class Transcript:
    path: Path

    def write(self, text: str) -> None:
        """Appends one timestamped line per non-blank line of text; a failing disk never fails the install."""
        stamp = datetime.now().isoformat(timespec="seconds")
        body = "".join(f"{stamp} {line}\n" for line in text.splitlines() if line.strip())
        try:
            with self.path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(body)
        except OSError:
            pass


def _prune(directory: Path) -> None:
    for old in sorted(directory.glob(f"{PREFIX}*{SUFFIX}"))[:-KEPT_TRANSCRIPTS]:
        old.unlink(missing_ok=True)


def open_transcript(directory: Path, stamp: str) -> Transcript | None:
    """Creates the 0600 file in a 0700 directory and drops all but the newest KEPT_TRANSCRIPTS; None when it cannot."""
    path = directory / f"{PREFIX}{stamp}{SUFFIX}"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        _prune(directory)
    except OSError:
        return None
    return Transcript(path)


def _text(stream: Any) -> str:
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream if isinstance(stream, str) else ""


def _command(argv: Any) -> str:
    return shlex.join(argv) if isinstance(argv, list | tuple) else str(argv)


def recording[R](run: Callable[..., R], write: Callable[[str], None]) -> Callable[..., R]:
    """Wraps a command runner so each call, its exit code and any output it captured reach `write`.

    Input passed to the command is never recorded, and output a command sends straight to the terminal is not seen."""

    def record(argv: Any, **kwargs: Any) -> R:
        try:
            result = run(argv, **kwargs)
        except BaseException as error:
            write(f"$ {_command(argv)} raised {type(error).__name__}: {error}")
            raise
        write(f"$ {_command(argv)} -> exit {getattr(result, 'returncode', '?')}")
        for stream in ("stdout", "stderr"):
            write(_text(getattr(result, stream, None)))
        return result

    return record
