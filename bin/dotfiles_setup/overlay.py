"""Detects an optional local-overlay root — a sibling private repo, or a bare
local directory — and merges its content over the public repo's generic
defaults. One mechanism serves a stranger's plain fork (no overlay found)
and a work machine with ~/.dotfiles-private cloned alongside alike."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_OVERLAY_ROOT = Path.home() / ".dotfiles-private"
LOCAL_OVERLAY_ROOT = Path.home() / ".config" / "dotfiles" / "local-overlay"


def find_overlay_root() -> Path | None:
    env_override = os.environ.get("DOTFILES_PRIVATE_ROOT")
    if env_override:
        candidate = Path(env_override)
        return candidate if candidate.is_dir() else None
    if DEFAULT_OVERLAY_ROOT.is_dir():
        return DEFAULT_OVERLAY_ROOT
    if LOCAL_OVERLAY_ROOT.is_dir():
        return LOCAL_OVERLAY_ROOT
    return None


def overlay_package_names(overlay_root: Path | None, preset_name: str) -> tuple[str, ...]:
    if overlay_root is None:
        return ()
    fragment = overlay_root / "packages" / f"{preset_name}_extra.txt"
    if not fragment.is_file():
        return ()
    names = {
        line.strip()
        for line in fragment.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    return tuple(sorted(names))


def merge_claude_settings(base: dict, overlay: dict | None) -> dict:
    if overlay is None:
        return base
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_claude_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_claude_settings(base_path: Path, overlay_root: Path | None, preset_name: str) -> dict:
    base = json.loads(base_path.read_text()) if base_path.is_file() else {}
    overlay_path = overlay_root / "claude-profiles" / f"{preset_name}.json" if overlay_root else None
    overlay = (
        json.loads(overlay_path.read_text())
        if overlay_path and overlay_path.is_file()
        else None
    )
    return merge_claude_settings(base, overlay)
