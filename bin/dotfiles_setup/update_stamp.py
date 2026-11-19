"""The stamp `dfctl-update-check` (zsh) reads: a successful `dfctl apply` resets its reminder clock."""
from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from dotfiles_setup.fsutil import atomic_write_text
from dotfiles_setup.log import Logger

STAMP_MODE = 0o600
DIRECTORY_MODE = 0o700


def stamp_path(environ: Mapping[str, str], home: Path) -> Path:
    state_home = environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
    return Path(state_home) / "dotfiles" / "update-check"


def stamp_text(now: datetime) -> str:
    return f"LAST_EPOCH={int(now.timestamp() // 86400)}\n"


def record_apply(logger: Logger, home: Path, now: datetime) -> None:
    path = stamp_path(os.environ, home)
    try:
        path.parent.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
        atomic_write_text(path, stamp_text(now), STAMP_MODE)
    except OSError as error:
        logger.warn(f"Could not write the update reminder stamp {path}: {error}")
