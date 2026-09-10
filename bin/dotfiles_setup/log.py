"""Logging/output primitives. Port of bin/lib/log.sh."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

_RESET = "\033[0m"
_GREEN = "\033[0;32m"
_YELLOW = "\033[0;33m"
_CYAN = "\033[0;36m"
_RED = "\033[0;31m"


@dataclass(frozen=True)
class Logger:
    """Verbosity/dry-run-aware output, threaded explicitly instead of via
    global bash variables (VERBOSITY/DRY_RUN in the original)."""

    dry_run: bool
    verbosity: int = 0

    def info(self, message: str) -> None:
        if self.verbosity >= 1:
            print(f"{_CYAN}[INFO] {message}{_RESET}")

    def success(self, message: str) -> None:
        if self.verbosity >= 1:
            print(f"{_GREEN}[SUCCESS] {message}{_RESET}")

    def banner(self, message: str) -> None:
        print(f"{_GREEN}[SUCCESS] {message}{_RESET}")

    def step(self, message: str) -> None:
        print(f"{_CYAN}==> {message}{_RESET}")

    def warn(self, message: str) -> None:
        print(f"{_YELLOW}[WARNING] {message}{_RESET}")

    def error(self, message: str) -> None:
        print(f"{_RED}[ERROR] {message}{_RESET}", file=sys.stderr)

    def dry_run_notice(self, message: str) -> bool:
        if self.dry_run:
            print(f"{_YELLOW}[DRY-RUN] {message}{_RESET}")
            return True
        return False

    def quiet_run(
        self, argv: list[str], run=subprocess.run
    ) -> subprocess.CompletedProcess:
        """Runs argv, suppressing output unless verbosity>=2; failures always
        surface captured output first. Combines stdout+stderr after the fact
        (unlike bash's `2>&1`, this doesn't preserve true interleaving order —
        acceptable since only failure output needs to be seen, not ordered)."""
        if self.verbosity >= 2:
            return run(argv)
        result = run(argv, capture_output=True, text=True)
        if result.returncode != 0:
            combined = (result.stdout or "") + (result.stderr or "")
            print(combined, file=sys.stderr, end="")
        return result
