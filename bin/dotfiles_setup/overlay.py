"""Detects an optional local-overlay root — a sibling private repo, or a bare
local directory — and merges its content over the public repo's generic
defaults. One mechanism serves a stranger's plain fork (no overlay found)
and a work machine with ~/.dotfiles-private cloned alongside alike."""
from __future__ import annotations

import functools
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


def _union(base: list[Any], extra: list[Any]) -> list[Any]:
    result = list(base)
    for item in extra:
        if item not in result:
            result.append(item)
    return result


def merge_settings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    return _merge(base, overlay, union_lists=True)


def _read_layer(path: Path | None) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path is not None and path.is_file() else {}


def load_preset_settings(
    base_path: Path, profile_path: Path | None, overlay_root: Path | None, preset_name: str,
) -> dict[str, Any]:
    """Merges base, the preset's profile, then the overlay's settings and its `<preset>.json`; later layers win."""
    overlay_files = (
        (overlay_root / "claude-settings" / "settings.json", overlay_root / "claude-profiles" / f"{preset_name}.json")
        if overlay_root is not None else ()
    )
    layers = [_read_layer(path) for path in (profile_path, *overlay_files)]
    return functools.reduce(merge_settings, layers, json.loads(base_path.read_text(encoding="utf-8")))
