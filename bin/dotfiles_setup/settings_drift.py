"""Detects hand edits to the generated ~/.claude/settings.json by comparing it
with the text the last install wrote."""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

BASELINE_NAME = "settings.last-generated.json"


def render(settings: dict[str, Any]) -> str:
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def baseline_path(state_dir: Path) -> Path:
    return state_dir / BASELINE_NAME


def record_baseline(state_dir: Path, rendered: str) -> None:
    path = baseline_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _normalized(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    except json.JSONDecodeError:
        return text


def drift_diff(target: Path, state_dir: Path) -> str:
    """Unified diff of the last generated settings against `target`; empty
    when they match, or when there is nothing to compare (no baseline yet,
    target missing, or target a symlink)."""
    baseline = baseline_path(state_dir)
    if target.is_symlink() or not target.is_file() or not baseline.is_file():
        return ""
    before = _normalized(baseline.read_text(encoding="utf-8", errors="replace"))
    after = _normalized(target.read_text(encoding="utf-8", errors="replace"))
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="last generated",
        tofile=str(target),
    ))