"""Loads the pinned release specs from packages/release_specs.json and rejects a malformed one."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.result import Err, Ok, Result

KINDS = ("targz", "zip", "deb")
REQUIRED_FIELDS = ("package", "name", "version", "url", "cache_key", "kind")
OPTIONAL_FIELDS = ("binary",)


@dataclass(frozen=True)
class SpecData:
    """One pinned release; `url` and `cache_key` are templates over `{version}`."""

    package: str
    name: str
    version: str
    url: str
    cache_key: str
    kind: str
    binary: str | None = None

    @property
    def download_url(self) -> str:
        return self.url.format(version=self.version)

    @property
    def artifact_name(self) -> str:
        return self.cache_key.format(version=self.version)


def _spec(entry: object, index: int) -> Result[SpecData]:
    where = f"release spec #{index + 1}"
    if not isinstance(entry, dict):
        return Err(f"{where} is not an object.")
    unknown = sorted(set(entry) - {*REQUIRED_FIELDS, *OPTIONAL_FIELDS})
    if unknown:
        return Err(f"{where} has unknown fields: {', '.join(unknown)}.")
    bad = [f for f in (*REQUIRED_FIELDS, *(f for f in OPTIONAL_FIELDS if f in entry)) if not _non_empty_str(entry.get(f))]
    if bad:
        return Err(f"{where} needs non-empty string values for: {', '.join(bad)}.")
    return _checked(SpecData(**entry), where)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _checked(spec: SpecData, where: str) -> Result[SpecData]:
    if spec.kind not in KINDS:
        return Err(f"{where} ({spec.package}) has kind '{spec.kind}'; expected one of {', '.join(KINDS)}.")
    if not spec.url.startswith("https://"):
        return Err(f"{where} ({spec.package}) must use an https:// url.")
    try:
        _ = (spec.download_url, spec.artifact_name)
    except (KeyError, IndexError, ValueError) as error:
        return Err(f"{where} ({spec.package}) may only use {{version}} in url and cache_key: {error!r}.")
    return Ok(spec)


def parse_specs(text: str) -> Result[tuple[SpecData, ...]]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        return Err(f"Release specs are not valid JSON: {error}.")
    if not isinstance(raw, list) or not raw:
        return Err("Release specs must be a non-empty list.")
    specs: list[SpecData] = []
    for index, entry in enumerate(raw):
        match _spec(entry, index):
            case Err() as error:
                return error
            case Ok(value=spec):
                specs.append(spec)
    packages = [s.package for s in specs]
    duplicates = sorted({p for p in packages if packages.count(p) > 1})
    if duplicates:
        return Err(f"Release specs repeat packages: {', '.join(duplicates)}.")
    return Ok(tuple(specs))


def load_specs(path: Path) -> Result[tuple[SpecData, ...]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return Err(f"Could not read {path}: {error}.")
    return parse_specs(text)
