"""Removes the tools `packages/uninstall.txt` names, through a fixed registry of tested actions; the file never names a command or path."""
from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dotfiles_setup.result import Err, Ok, Result
from dotfiles_setup.tooling import Tooling

BASE_FILE = Path("packages") / "uninstall.txt"
EXTRAS_FILE = Path("packages") / "uninstall_extra.txt"


@dataclass(frozen=True)
class UvTool:
    name: str


@dataclass(frozen=True)
class PipxTool:
    name: str


@dataclass(frozen=True)
class ClaudeMcp:
    name: str


@dataclass(frozen=True)
class HomePath:
    relative: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative)
        if not path.parts or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"HomePath needs a non-empty relative path without '..': {self.relative!r}")


type Action = UvTool | PipxTool | ClaudeMcp | HomePath

REGISTRY: dict[str, tuple[Action, ...]] = {
    "serena": (UvTool("serena-agent"), PipxTool("serena-agent"), ClaudeMcp("serena"), HomePath(".serena")),
    "cozempic": (
        UvTool("cozempic"), PipxTool("cozempic"), HomePath(".cozempic"), HomePath(".claude/cozempic-metrics"),
        HomePath(".claude/cozempic-sessions.json"), HomePath(".claude/cozempic-sessions.json.lock"),
        HomePath(".claude/cozempic-active-sessions.json"), HomePath(".claude/cozempic-active-sessions.json.lock"),
    ),
}


def parse(text: str) -> tuple[str, ...]:
    lines = (line.strip() for line in text.splitlines())
    return tuple(dict.fromkeys(line for line in lines if line and not line.startswith("#")))


def _read(path: Path) -> Result[tuple[str, ...]]:
    if not path.exists():
        return Ok(())
    try:
        return Ok(parse(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError) as exc:
        return Err(f"Cannot read {path}: {exc}")


def load(dotfiles_dir: Path, overlay_root: Path | None) -> Result[tuple[str, ...]]:
    """The base list followed by the overlay's extras, first duplicate kept; a missing file is empty."""
    extras = Ok(()) if overlay_root is None else _read(overlay_root / EXTRAS_FILE)
    return _read(dotfiles_dir / BASE_FILE).and_then(
        lambda base: extras.map(lambda more: tuple(dict.fromkeys([*base, *more])))
    )


def unknown(names: Sequence[str]) -> tuple[str, ...]:
    return tuple(name for name in names if name not in REGISTRY)


def _listed_names(t: Tooling, argv: list[str]) -> set[str]:
    listing = t.run(argv, capture_output=True, text=True).stdout or ""
    return {line.split()[0] for line in listing.splitlines() if line and not line.startswith(("-", " "))}


def _mcp_names(home: Path) -> set[str]:
    """Reads `~/.claude.json` instead of asking `claude mcp get`, which health-checks the server by starting it."""
    try:
        data = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return set(servers) if isinstance(servers, dict) else set()


def is_present(t: Tooling, action: Action) -> bool:
    match action:
        case UvTool(name=name):
            return name in _listed_names(t, ["uv", "tool", "list"])
        case PipxTool(name=name):
            return name in _listed_names(t, ["pipx", "list", "--short"])
        case ClaudeMcp(name=name):
            return name in _mcp_names(t.home)
        case HomePath(relative=relative):
            path = t.home / relative
            return path.exists() or path.is_symlink()


def pending(t: Tooling, names: Sequence[str]) -> tuple[str, ...]:
    """The registered names with at least one action whose target is still there. Read-only."""
    return tuple(name for name in names if any(is_present(t, a) for a in REGISTRY.get(name, ())))


def _remove_path(home: Path, path: Path) -> bool:
    """Deletes a file, a symlink (never its target) or a directory tree; refuses a path whose parent resolves outside `home`, so a symlinked parent cannot redirect the delete; False when the delete fails."""
    if not path.parent.resolve().is_relative_to(home.resolve()):
        return False
    try:
        path.unlink() if path.is_symlink() or path.is_file() else shutil.rmtree(path)
    except OSError:
        return False
    return True


def remove_action(t: Tooling, action: Action) -> bool:
    match action:
        case UvTool(name=name):
            return t.run(["uv", "tool", "uninstall", name], capture_output=True).returncode == 0
        case PipxTool(name=name):
            return t.run(["pipx", "uninstall", name], capture_output=True).returncode == 0
        case ClaudeMcp(name=name):
            return t.run(["claude", "mcp", "remove", name, "--scope", "user"], capture_output=True).returncode == 0
        case HomePath(relative=relative):
            return _remove_path(t.home, t.home / relative)


def remove(t: Tooling, name: str) -> bool:
    """Runs every present action of a registered name, all of them even after a failure; False if any failed or the name is unknown."""
    actions = REGISTRY.get(name)
    if actions is None:
        return False
    results = [remove_action(t, action) for action in actions if is_present(t, action)]
    return all(results)
