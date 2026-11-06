import shutil
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from itertools import chain, count
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
    return all(line.strip() != HEADER for line in path.read_text().splitlines())


def render(optouts: frozenset[str]) -> str:
    return "".join(f"{line}\n" for line in (HEADER, *sorted(optouts)))


def plan_migration(path: Path, combined: Sequence[str]) -> MigrationResult:
    fork = frozenset(package_names(path.read_text()))
    wanted = frozenset(combined)
    return MigrationResult(wanted - fork, tuple(sorted(fork - wanted)))


def _free_backup_path(backup: Path, name: str) -> Path:
    candidates = chain((backup / name,), (backup / f"{name}.{n}" for n in count(1)))
    return next(p for p in candidates if not p.exists())


def write_migration(path: Path, optouts: frozenset[str], backup: Path) -> Path:
    """Copies the legacy file to a new path under backup, rewrites it as opt-outs and returns the copy's path."""
    backup.mkdir(parents=True, exist_ok=True)
    saved = _free_backup_path(backup, path.name)
    shutil.copy2(path, saved)
    staged = path.with_name(f"{path.name}.tmp")
    try:
        staged.write_text(render(optouts))
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)
    return saved


def restore_from_backup(path: Path, saved: Path) -> None:
    shutil.copy2(saved, path)


def migrate(
    path: Path, combined: Sequence[str], backup: Path, *, dry_run: bool
) -> MigrationResult:
    result = plan_migration(path, combined)
    if not dry_run:
        write_migration(path, result.optouts, backup)
    return result


def other_preset_files(package_dir: Path, keep: str, preset_names: Collection[str]) -> tuple[Path, ...]:
    files = (package_dir / f"{name}.txt" for name in preset_names if name != keep)
    return tuple(sorted(p for p in files if p.is_file()))


def move_to_backup(files: Sequence[Path], backup: Path) -> None:
    if files:
        backup.mkdir(parents=True, exist_ok=True)
    for p in files:
        shutil.move(str(p), backup / p.name)
