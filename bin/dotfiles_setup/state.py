"""Per-machine setup state, persisted outside the repo (~/.config/dotfiles)
so it survives across re-clones/forks and never enters git history."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_DIR = Path.home() / ".config" / "dotfiles"
STATE_FILE = STATE_DIR / "state.json"
PACKAGE_DIR = STATE_DIR / "packages"


@dataclass(frozen=True)
class MachineState:
    preset_name: str
    backend: str
    package_file: str
    applied_package_names: tuple[str, ...]
    overlay_root: str | None
    created_at: str
    updated_at: str


def load_state(state_file: Path | None = None) -> MachineState | None:
    # A Path = STATE_FILE default would bind at def-time, before any test or
    # caller can monkeypatch STATE_FILE; resolving it in the body re-reads
    # the current module-level value on every call instead.
    state_file = state_file if state_file is not None else STATE_FILE
    if not state_file.is_file():
        return None
    data = json.loads(state_file.read_text())
    data["applied_package_names"] = tuple(data["applied_package_names"])
    return MachineState(**data)


def save_state(state: MachineState, state_file: Path | None = None) -> None:
    state_file = state_file if state_file is not None else STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(asdict(state), indent=2) + "\n")
