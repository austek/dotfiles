"""The single PATH list: parses `packages/path_dirs.txt` plus the overlay's extras and renders it per consumer."""
from __future__ import annotations

from pathlib import Path

from dotfiles_setup.result import Err, Ok, Result

BASE_FILE = Path("packages") / "path_dirs.txt"
EXTRAS_FILE = Path("packages") / "path_dirs_extra.txt"
HOME_PREFIX = "~/"


def _entry(line: str) -> str | None:
    text = line.strip()
    return None if not text or text.startswith("#") else text


def _is_directory_entry(entry: str) -> bool:
    return entry.startswith((HOME_PREFIX, "/"))


def _dedupe(entries: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(entries))


def parse(text: str, source: str = "PATH list") -> Result[tuple[str, ...]]:
    """Entries in file order, first duplicate kept. Errs on an entry that is neither `~/…` nor absolute, naming its line."""
    entries: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        entry = _entry(line)
        if entry is None:
            continue
        if not _is_directory_entry(entry):
            return Err(f"{source}: line {number}: '{entry}' must start with '~/' or '/'.")
        if ":" in entry:
            return Err(f"{source}: line {number}: '{entry}' must not contain ':', the PATH separator.")
        entries.append(entry)
    return Ok(_dedupe(entries))


def _read(path: Path) -> Result[tuple[str, ...]]:
    try:
        return parse(path.read_text(encoding="utf-8"), source=str(path))
    except (OSError, UnicodeError) as exc:
        return Err(f"Cannot read {path}: {exc}")


def _extras(overlay_root: Path | None) -> Result[tuple[str, ...]]:
    if overlay_root is None or not (overlay_root / EXTRAS_FILE).is_file():
        return Ok(())
    return _read(overlay_root / EXTRAS_FILE)


def _non_empty(base: tuple[str, ...], source: Path) -> Result[tuple[str, ...]]:
    return Ok(base) if base else Err(f"{source}: no directories listed; Claude and the foothold unit would get an empty PATH.")


def load(dotfiles_dir: Path, overlay_root: Path | None) -> Result[tuple[str, ...]]:
    """The base list followed by the overlay's extras, first duplicate kept. A missing or empty base file is an error."""
    source = dotfiles_dir / BASE_FILE
    return _read(source).and_then(lambda base: _non_empty(base, source)).and_then(
        lambda base: _extras(overlay_root).map(lambda extras: _dedupe([*base, *extras]))
    )


def for_env(entries: tuple[str, ...], home: Path) -> str:
    return ":".join(f"{home}/{entry[len(HOME_PREFIX):]}" if entry.startswith(HOME_PREFIX) else entry for entry in entries)


def _systemd_entry(entry: str) -> str:
    """A literal `%` is doubled so systemd does not read it as a specifier; the `%h` prefix for `~/` stays one."""
    if entry.startswith(HOME_PREFIX):
        return "%h/" + entry[len(HOME_PREFIX):].replace("%", "%%")
    return entry.replace("%", "%%")


def for_systemd(entries: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_systemd_entry(entry) for entry in entries)
