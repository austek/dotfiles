"""The value types the doctor checks return."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Finding:
    check: str
    text: str
    affects: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    advice: str = ""

    @property
    def fixable(self) -> bool:
        return bool(self.commands)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "text": self.text,
            "affects": list(self.affects),
            "commands": [list(argv) for argv in self.commands],
            "advice": self.advice,
        }


@dataclass(frozen=True)
class CheckOutcome:
    findings: tuple[Finding, ...] = ()
    skipped: str | None = None
