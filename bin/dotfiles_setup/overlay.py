"""Detects an optional local-overlay root — a sibling private repo, or a bare
local directory — and merges its content over the public repo's generic
defaults. One mechanism serves a stranger's plain fork (no overlay found)
and a work machine with ~/.dotfiles-private cloned alongside alike."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotfiles_setup.presets import package_names

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
    return tuple(sorted(package_names(fragment.read_text())))


def _merge(base: dict[str, Any], overlay: dict[str, Any], union_lists: bool) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _merge(current, value, union_lists)
        elif union_lists and isinstance(value, list) and isinstance(current, list):
            merged[key] = _union(current, value)
        else:
            merged[key] = value
    return merged


def merge_claude_settings(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    return base if overlay is None else _merge(base, overlay, union_lists=False)


def load_claude_settings(base_path: Path, overlay_root: Path | None, preset_name: str) -> dict[str, Any]:
    base = json.loads(base_path.read_text()) if base_path.is_file() else {}
    overlay_path = overlay_root / "claude-profiles" / f"{preset_name}.json" if overlay_root else None
    overlay = (
        json.loads(overlay_path.read_text())
        if overlay_path and overlay_path.is_file()
        else None
    )
    return merge_claude_settings(base, overlay)


def _union(base: list[Any], extra: list[Any]) -> list[Any]:
    result = list(base)
    for item in extra:
        if item not in result:
            result.append(item)
    return result


def merge_settings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    return _merge(base, overlay, union_lists=True)


def load_settings(base_path: Path, overlay_root: Path | None) -> dict[str, Any]:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    overlay_path = overlay_root / "claude-settings" / "settings.json" if overlay_root else None
    if overlay_path is None or not overlay_path.is_file():
        return base
    return merge_settings(base, json.loads(overlay_path.read_text(encoding="utf-8")))
