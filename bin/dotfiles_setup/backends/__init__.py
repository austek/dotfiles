"""Package-manager backend contract. AptBackend (backends/apt.py) is the only
implementation today; a macOS/Homebrew backend is explicitly out of scope for
this project — this Protocol exists so adding one later doesn't require
touching presets.py, state.py, or cli.py's orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
