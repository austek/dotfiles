"""Preset manifests: what a machine installs, keyed by name."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.result import Err, Ok, Result


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    package_files: tuple[str, ...]
    backend_overrides: dict[str, dict[str, str]]
    claude_settings: str | None


def load_preset(presets_dir: Path, name: str) -> Result[Preset]:
    manifest_path = presets_dir / f"{name}.json"
    if Path(name).name != name or not manifest_path.is_file():
        return Err(f"No preset named '{name}' in {presets_dir}")
    data = json.loads(manifest_path.read_text())
    return Ok(Preset(
        name=name,
        description=data.get("description", ""),
        package_files=tuple(data.get("package_files", ())),
        backend_overrides=data.get("backend_overrides", {}),
        claude_settings=data.get("claude_settings"),
    ))


def package_names(text: str) -> set[str]:
    stripped = (line.strip() for line in text.splitlines())
    return {line for line in stripped if line and not line.startswith("#")}


def resolve_packages(packages_dir: Path, preset: Preset) -> Result[tuple[str, ...]]:
    paths = [packages_dir / filename for filename in preset.package_files]
    missing = next((path for path in paths if not path.is_file()), None)
    if missing is not None:
        return Err(f"Preset '{preset.name}' declares missing package file: {missing}")
    return Ok(tuple(sorted(set().union(*(package_names(path.read_text()) for path in paths)))))
