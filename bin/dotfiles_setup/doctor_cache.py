"""The summary of the last doctor run: ids and text only, never commands, so a fix never replays it."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from dotfiles_setup.findings import Finding
from dotfiles_setup.fsutil import atomic_write_text
from dotfiles_setup.update_stamp import DIRECTORY_MODE, STAMP_MODE, stamp_path

CACHE_VERSION = 1


def cache_path(environ: Mapping[str, str], home: Path) -> Path:
    return stamp_path(environ, home).with_name("doctor.json")


def _well_formed(entry: Any) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("check"), str) and isinstance(entry.get("text"), str)


def _stored_findings(path: Path) -> list[dict[str, str]]:
    try:
        stored = json.loads(path.read_text())["findings"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [entry for entry in stored if _well_formed(entry)] if isinstance(stored, list) else []


def write_cache(
    path: Path, results: Mapping[str, tuple[Finding, ...]], now: datetime, *, merge: bool
) -> None:
    kept = [f for f in _stored_findings(path) if f.get("check") not in results] if merge else []
    fresh = [{"check": f.check, "text": f.text} for found in results.values() for f in found]
    document = {"v": CACHE_VERSION, "checkedAt": int(now.timestamp()), "findings": [*kept, *fresh]}
    path.parent.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(document) + "\n", STAMP_MODE)
