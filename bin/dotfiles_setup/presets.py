"""Preset manifests: what a machine installs, keyed by name. Replaces the
--preset-conditional package-file selection previously hardcoded in
bin/lib/apt.sh's determine_packages_to_install."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    package_files: tuple[str, ...]
    backend_overrides: dict[str, dict[str, str]]
    claude_settings: str | None


def load_preset(presets_dir: Path, name: str) -> Preset:
    manifest_path = presets_dir / f"{name}.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"No preset named '{name}' in {presets_dir}")
    data = json.loads(manifest_path.read_text())
    return Preset(
        name=name,
        description=data.get("description", ""),
        package_files=tuple(data.get("package_files", ())),
        backend_overrides=data.get("backend_overrides", {}),
        claude_settings=data.get("claude_settings"),
    )


def resolve_packages(packages_dir: Path, preset: Preset) -> tuple[str, ...]:
    names: set[str] = set()
    for filename in preset.package_files:
        file_path = packages_dir / filename
        if not file_path.is_file():
            continue
        for line in file_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                names.add(stripped)
    return tuple(sorted(names))
