"""Per-machine setup state, persisted outside the repo (~/.config/dotfiles)
so it survives across re-clones/forks and never enters git history."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def state_dir() -> Path:
    return Path.home() / ".config" / "dotfiles"


def state_file(base: Path | None = None) -> Path:
    return (base if base is not None else state_dir()) / "state.json"


def package_dir(base: Path | None = None) -> Path:
    return (base if base is not None else state_dir()) / "packages"


@dataclass(frozen=True)
class MachineState:
    preset_name: str
    backend: str
    package_file: str
    applied_package_names: tuple[str, ...]
    overlay_root: str | None
    created_at: str
    updated_at: str


def load_state(path: Path | None = None) -> MachineState | None:
    path = path if path is not None else state_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        data["applied_package_names"] = tuple(data["applied_package_names"])
        return MachineState(**data)
    except (OSError, ValueError, KeyError, TypeError):
        print(f"warning: ignoring unreadable state file {path}", file=sys.stderr)
        return None


def save_state(state: MachineState, path: Path | None = None) -> None:
    path = path if path is not None else state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n")
