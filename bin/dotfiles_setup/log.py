"""Logging/output primitives."""
from __future__ import annotations

import subprocess
import sys
import syslog
from dataclasses import dataclass
from functools import cache

from dotfiles_setup.transcript import Transcript

_RESET = "\033[0m"
_GREEN = "\033[0;32m"
_YELLOW = "\033[0;33m"
_CYAN = "\033[0;36m"
_RED = "\033[0;31m"
SYSLOG_TAG = "dotfiles-setup"
_PRIORITIES = {
    "info": syslog.LOG_INFO,
    "notice": syslog.LOG_NOTICE,
    "warning": syslog.LOG_WARNING,
    "error": syslog.LOG_ERR,
}


@cache
def _open_syslog() -> None:
    syslog.openlog(SYSLOG_TAG, syslog.LOG_PID, syslog.LOG_USER)


@dataclass(frozen=True)
class Logger:
    """Verbosity/dry-run-aware output, threaded explicitly instead of via
    global bash variables (VERBOSITY/DRY_RUN in the original).

    Every message also goes to syslog (`journalctl -t dotfiles-setup`, `/var/log/syslog` where rsyslog runs),
    whatever the verbosity, so a run can be reconstructed after the terminal output is gone."""

    dry_run: bool
    verbosity: int = 0
    transcript: Transcript | None = None

    def record(self, message: str, level: str = "info", *, transcribe: bool = True) -> None:
        """Writes to syslog, one entry per non-blank line, and to the transcript unless the caller's runner already did."""
        _open_syslog()
        for line in filter(str.strip, message.splitlines()):
            syslog.syslog(_PRIORITIES[level], line)
        if transcribe:
            self.transcribe(message)

    def transcribe(self, text: str) -> None:
        if self.transcript is not None:
            self.transcript.write(text)

    def info(self, message: str) -> None:
        self.record(message)
        if self.verbosity >= 1:
            print(f"{_CYAN}[INFO] {message}{_RESET}")

    def success(self, message: str) -> None:
        self.record(message)
        if self.verbosity >= 1:
            print(f"{_GREEN}[SUCCESS] {message}{_RESET}")

    def banner(self, message: str) -> None:
        self.record(message)
        print(f"{_GREEN}[SUCCESS] {message}{_RESET}")

    def step(self, message: str) -> None:
        self.record(message, "notice")
        print(f"{_CYAN}==> {message}{_RESET}")

    def warn(self, message: str) -> None:
        self.record(message, "warning")
        print(f"{_YELLOW}[WARNING] {message}{_RESET}")

    def error(self, message: str) -> None:
        self.record(message, "error")
        print(f"{_RED}[ERROR] {message}{_RESET}", file=sys.stderr)

    def dry_run_notice(self, message: str) -> bool:
        if self.dry_run:
            self.record(f"[dry-run] {message}")
            print(f"{_YELLOW}[DRY-RUN] {message}{_RESET}")
            return True
        return False

    def quiet_run(
        self, argv: list[str], run=subprocess.run, cwd=None
    ) -> subprocess.CompletedProcess:
        """Runs argv, suppressing output unless verbosity>=2; failures always
        surface captured output first. Combines stdout+stderr after the fact
        (unlike bash's `2>&1`, this doesn't preserve true interleaving order —
        acceptable since only failure output needs to be seen, not ordered)."""
        where = {} if cwd is None else {"cwd": cwd}
        if self.verbosity >= 2:
            streamed = run(argv, **where)
            if streamed.returncode != 0:
                self.record(f"{' '.join(argv)} exited {streamed.returncode}", "warning", transcribe=False)
            return streamed
        result = run(argv, capture_output=True, text=True, **where)
        if result.returncode != 0:
            combined = (result.stdout or "") + (result.stderr or "")
            self.record(f"{' '.join(argv)} exited {result.returncode}\n{combined}", "warning", transcribe=False)
            print(combined, file=sys.stderr, end="")
        return result
