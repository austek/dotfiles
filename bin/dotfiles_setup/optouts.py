import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.presets import package_names

HEADER = "# dotfiles-setup opt-outs v1"


@dataclass(frozen=True)
class MigrationResult:
    optouts: frozenset[str]
    fork_only: tuple[str, ...]


def backup_dir(state_home: Path, stamp: str) -> Path:
    return state_home / "package-backups" / stamp


def read_optouts(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    return frozenset(package_names(path.read_text()))


def is_legacy(path: Path) -> bool:
    if not path.is_file():
        return False
    lines = (line.strip() for line in path.read_text().splitlines())
    return next((line for line in lines if line), "") != HEADER


def render(optouts: frozenset[str]) -> str:
    return "".join(f"{line}\n" for line in (HEADER, *sorted(optouts)))


def migrate(
    path: Path, combined: Sequence[str], backup: Path, *, dry_run: bool
) -> MigrationResult:
    fork = frozenset(package_names(path.read_text()))
    wanted = frozenset(combined)
    result = MigrationResult(wanted - fork, tuple(sorted(fork - wanted)))
    if not dry_run:
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup / path.name)
        path.write_text(render(result.optouts))
    return result


def retire_other_presets(
    package_dir: Path, keep: str, backup: Path, *, dry_run: bool
) -> tuple[str, ...]:
    others = sorted(p for p in package_dir.glob("*.txt") if p.stem != keep)
    if others and not dry_run:
        backup.mkdir(parents=True, exist_ok=True)
        for p in others:
            shutil.move(str(p), backup / p.name)
    return tuple(p.name for p in others)
