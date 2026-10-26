"""Package-manager backend contract. AptBackend (backends/apt.py) is the only
implementation today; a macOS/Homebrew backend is explicitly out of scope for
this project — this Protocol exists so adding one later doesn't require
touching presets.py, state.py, or cli.py's orchestration."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class InstallResult:
    succeeded: bool
    returncode: int
    stdout: str
    rollback_pending: bool = False


@runtime_checkable
class Backend(Protocol):
    name: str

    def detect(self) -> bool: ...
    def resolve_name(self, logical_name: str) -> str: ...
    def install(
        self,
        package_file: Path,
        *,
        preset_name: str,
        dry_run: bool,
        private_root: Path | None = None,
        verbosity: int = 0,
        step_hooks: Mapping[str, Callable[[], bool]] | None = None,
        run: Callable[..., Any] = ...,
    ) -> InstallResult: ...
    def print_completion(self, *, dry_run: bool, run: Callable[..., Any] = ...) -> None: ...
