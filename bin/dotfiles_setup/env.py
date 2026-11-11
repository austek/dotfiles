"""The collaborators and locations a dotfiles-setup command runs against."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotfiles_setup import checksums, state, tooling
from dotfiles_setup.backends import Backend
from dotfiles_setup.log import Logger
from dotfiles_setup.transcript import recording

RunFn = Callable[..., Any]
BackendFactory = Callable[[Path, dict[str, str]], Backend]


def _dotfiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _home() -> Path:
    return Path.home()


def _claude_home() -> Path:
    return Path.home() / ".claude"


def _apt_backend(dotfiles_dir: Path, overrides: dict[str, str]) -> Backend:
    from dotfiles_setup.backends.apt import AptBackend

    return AptBackend(dotfiles_dir=dotfiles_dir, backend_overrides=overrides)


@dataclass(frozen=True)
class Env:
    """Collaborators and locations main() uses; defaults resolve when Env() is built, so tests can inject."""

    run: RunFn = field(default_factory=lambda: tooling.run_command)
    clock: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(UTC))
    home: Path = field(default_factory=lambda: _home())
    claude_home: Path = field(default_factory=lambda: _claude_home())
    state_dir: Path = field(default_factory=lambda: state.state_dir())
    dotfiles_dir: Path = field(default_factory=lambda: _dotfiles_dir())
    backend_factory: BackendFactory = _apt_backend
    euid: Callable[[], int] = os.geteuid

    def now_iso(self) -> str:
        return self.clock().isoformat()


def _tooling(logger: Logger, env: Env) -> tooling.Tooling:
    run = env.run if logger.transcript is None else recording(env.run, logger.transcribe)
    return tooling.Tooling(
        logger, env.home, run=run,
        fetch=tooling.fetch_https, fetch_bytes=tooling.fetch_bytes_https,
        download=tooling.download_https, redirect=tooling.redirect_location,
        checksums=checksums.load(env.dotfiles_dir / "packages" / checksums.FILE_NAME),
    )
